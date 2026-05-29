"""
SAM3 图像预处理器
用于入库前的背景去除和白色背景替换
"""
from dataclasses import dataclass
import os
import re
import numpy as np
import torch
from PIL import Image
from datetime import datetime
from typing import Optional
from transformers import Sam3VideoModel, Sam3VideoProcessor

from csrcqsf.modules.railway_parts.vector_search.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class SAM3PreprocessOutcome:
    result_image: Optional[Image.Image]
    original_item_name: str
    normalized_item_name: str
    prompt_candidates: list[str]
    selected_prompt: Optional[str]
    attempt_count: int


class SAM3Preprocessor:
    """SAM3 图像预处理器"""

    _NOISE_PATTERNS = [
        r"[左右前后]$",
        r"\((左|右|前|后|一|二|三)\)",
        r"[ABC]$",
        r"M\d+X\d+",
        r"DN\d+",
        r"(镀锌|达克罗|镀铬)",
        r"(组成|总成|组件)$",
    ]

    def __init__(
        self,
        model_path: str,
        mask_dilate: int = 20,
        bg_color: str = "white",
        device: str = "cuda",
        save_debug_images: bool = True,
        debug_output_dir: str = "logs/vector_db/sam3_debug"
    ):
        """
        初始化 SAM3 预处理器

        Args:
            model_path: SAM3 模型路径
            mask_dilate: Mask 膨胀像素数
            bg_color: 背景颜色 (white/black/gray)
            device: 设备 (cuda/cpu)
            save_debug_images: 是否保存调试图像
            debug_output_dir: 调试图像输出目录
        """
        self.mask_dilate = mask_dilate
        self.bg_color = bg_color
        self.device = device if torch.cuda.is_available() else "cpu"
        self.save_debug_images = save_debug_images
        self.debug_output_dir = debug_output_dir

        # 创建调试输出目录
        if self.save_debug_images:
            os.makedirs(self.debug_output_dir, exist_ok=True)

        logger.info(f"Loading SAM3 model from: {model_path}")
        self.model = Sam3VideoModel.from_pretrained(model_path).to(
            self.device, 
            dtype=torch.bfloat16 if self.device == "cuda" else torch.float32
        )
        self.processor = Sam3VideoProcessor.from_pretrained(model_path)
        self.model.eval()
        logger.info(f"SAM3 model loaded on {self.device}")

    def has_chinese(self, text: str) -> bool:
        """检测文本是否包含中文"""
        return bool(re.search(r'[\u4e00-\u9fff]', text))

    def translate_prompt(self, text: str) -> str:
        """
        翻译中文提示词为英文

        Args:
            text: 中文文本

        Returns:
            英文文本
        """
        # 先尝试使用 LLM 翻译
        try:
            from openai import OpenAI

            client = OpenAI(base_url="http://localhost:11434/v1", api_key="0")

            prompt = f"""将以下中文物体名称翻译成最简洁的英文核心词，用于图像分割。
            要求：
            1. 只返回核心英文单词，不要额外解释
            2. 去掉修饰词，保留最核心的物体类别
            3. 例如："特殊螺栓" -> "bolt"，"红色椅子" -> "chair"

            中文: {text}
            英文:"""

            message = client.chat.completions.create(
                model="qwen3:8b",
                max_tokens=128,
                temperature=0.7,
                top_p=0.8,
                reasoning_effort="none",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a translation helper. Reply with only one lowercase English noun. No explanation."
                    },
                    {
                        "role": "user",
                        "content": f"/no_think\n{prompt}"
                    },
                ],
            )
            english = message.choices[0].message.content.strip().lower()
            logger.debug(f"LLM translation: '{text}' -> '{english}'")
            logger.info(english)
            return english

        except Exception as e:
            logger.warning(f"LLM translation failed: {e}, using fallback dictionary")
            # 使用备用翻译字典
            return self._fallback_translate(text)

    def _fallback_translate(self, text: str) -> str:
        """
        备用翻译字典

        Args:
            text: 中文文本

        Returns:
            英文文本
        """
        # 简单的翻译字典
        translations = {
            "特殊螺栓": "bolt",
            "螺栓": "bolt",
            "螺丝": "screw",
            "螺母": "nut",
            "垫圈": "washer",
            "垫片": "washer",
            "管卡": "pipe clamp",
            "支座": "bracket",
            "标记": "sign",
            "物体": "object",
            "门锁": "lock",
        }

        for cn, en in translations.items():
            if cn in text:
                return en

        return "object"

    def normalize_item_name_for_prompt(self, item_name: str) -> str:
        """清洗名称中的方位、规格和工艺噪声，尽量保留核心物体类别。"""
        normalized = item_name.strip()
        for pattern in self._NOISE_PATTERNS:
            normalized = re.sub(pattern, "", normalized)
        normalized = re.sub(r"\s+", "", normalized).strip()
        return normalized or item_name.strip()

    def _sanitize_prompt_candidates(self, candidates: list[str]) -> list[str]:
        """去重并标准化候选提示词。"""
        cleaned: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            value = re.sub(r"\s+", " ", candidate.strip().lower())
            if not value:
                continue
            if value in seen:
                continue
            seen.add(value)
            cleaned.append(value)
        return cleaned

    def _fallback_prompt_candidates(self, text: str) -> list[str]:
        """在 LLM 不可用时，返回最小可用的兜底候选列表。"""
        fallback = self._fallback_translate(text).strip().lower()
        return self._sanitize_prompt_candidates([fallback, "object"])

    def generate_prompt_candidates(self, item_name: str) -> list[str]:
        """为 SAM3 生成有序候选提示词，首位尽量保持现有行为兼容。"""
        normalized_name = self.normalize_item_name_for_prompt(item_name)

        if not self.has_chinese(normalized_name):
            return self._sanitize_prompt_candidates([normalized_name, "object"])

        try:
            primary_prompt = self.extract_prompt_from_name(normalized_name)
        except Exception:
            logger.warning("Primary prompt generation failed, falling back to dictionary")
            return self._fallback_prompt_candidates(normalized_name)

        return self._sanitize_prompt_candidates(
            [
                primary_prompt,
                *self._fallback_prompt_candidates(normalized_name),
            ]
        )

    def extract_prompt_from_name(self, item_name: str) -> str:
        """
        从零件名称提取提示词

        Args:
            item_name: 零件名称

        Returns:
            英文提示词
        """
        logger.info(f"item_name:{item_name}")
        if self.has_chinese(item_name):
           
            return self.translate_prompt(item_name)
        return "object"

    def _segment_with_prompt(
        self,
        image: Image.Image,
        text_prompt: str,
    ) -> Optional[tuple[Image.Image, np.ndarray]]:
        """执行单个 prompt 的 SAM3 分割，成功则返回结果图和二值 mask。"""
        logger.debug(f"Using text prompt: {text_prompt}")

        if image.mode != "RGB":
            image = image.convert("RGB")

        video_frames = [image]
        session = self.processor.init_video_session(
            video=video_frames,
            inference_device=self.device,
            processing_device="cpu",
            video_storage_device="cpu",
            dtype=torch.bfloat16 if self.device == "cuda" else torch.float32,
        )
        session = self.processor.add_text_prompt(
            inference_session=session,
            text=text_prompt,
        )

        with torch.no_grad():
            outputs_per_frame = {}
            for out in self.model.propagate_in_video_iterator(
                inference_session=session,
                max_frame_num_to_track=1
            ):
                outputs_per_frame[out.frame_idx] = self.processor.postprocess_outputs(
                    session,
                    out,
                )

        if 0 not in outputs_per_frame:
            logger.warning(f"No output for frame 0: prompt={text_prompt}")
            return None

        output_data = outputs_per_frame[0]
        masks = output_data.get("masks", None)
        scores = output_data.get("scores", None)

        if masks is None or len(masks) == 0:
            logger.warning(f"No mask generated, returning None: prompt={text_prompt}")
            return None

        if hasattr(masks, 'shape') and len(masks.shape) >= 3:
            if scores is not None and len(scores) > 0:
                best_idx = torch.argmax(scores).item()
                logger.debug(
                    f"Using best mask (index {best_idx}, score {scores[best_idx]:.4f})"
                )
                combined = masks[best_idx].squeeze().float().cpu()
            else:
                logger.debug("Merging all masks")
                combined = torch.zeros(masks.shape[-2:], dtype=torch.float32)
                for i in range(masks.shape[0]):
                    combined = torch.maximum(combined, masks[i].squeeze().float().cpu())
        else:
            combined = masks.squeeze().float().cpu()

        mask = combined.numpy()
        img_np = np.array(image)
        h, w = img_np.shape[:2]

        if mask.shape != (h, w):
            import cv2
            mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST)

        mask = (mask > 0.5).astype(np.uint8)

        if self.mask_dilate > 0:
            import cv2
            kernel = np.ones((self.mask_dilate, self.mask_dilate), np.uint8)
            mask = cv2.dilate(mask, kernel, iterations=1)

        if self.bg_color == "white":
            bg = np.ones_like(img_np) * 255
        elif self.bg_color == "black":
            bg = np.zeros_like(img_np)
        else:
            bg = np.ones_like(img_np) * 128

        mask_3ch = np.stack([mask] * 3, axis=-1).astype(bool)
        result = np.where(mask_3ch, img_np, bg)

        ys, xs = np.where(mask > 0)
        if len(ys) == 0 or len(xs) == 0:
            logger.warning(f"Empty mask after processing: prompt={text_prompt}")
            return None

        y_min, y_max = ys.min(), ys.max()
        x_min, x_max = xs.min(), xs.max()
        result = result[y_min:y_max+1, x_min:x_max+1]
        result_image = Image.fromarray(result.astype(np.uint8))
        return result_image, mask

    def preprocess_image_with_metadata(
        self,
        image: Image.Image,
        item_name: str,
        image_id: Optional[int] = None,
    ) -> SAM3PreprocessOutcome:
        """按候选 prompt 顺序重试分割，并返回分割元数据。"""
        normalized_name = self.normalize_item_name_for_prompt(item_name)
        prompt_candidates = self.generate_prompt_candidates(item_name)
        attempt_count = 0

        try:
            for prompt in prompt_candidates:
                attempt_count += 1
                segment_result = self._segment_with_prompt(image, prompt)
                if segment_result is None:
                    continue

                result_image, mask = segment_result
                if self.save_debug_images and image_id is not None:
                    self._save_debug_images(
                        image,
                        mask,
                        result_image,
                        image_id,
                        item_name,
                        prompt,
                        normalized_item_name=normalized_name,
                        prompt_candidates=prompt_candidates,
                        selected_prompt=prompt,
                        prompt_attempt_count=attempt_count,
                        index_strategy="segmented_only",
                    )

                return SAM3PreprocessOutcome(
                    result_image=result_image,
                    original_item_name=item_name,
                    normalized_item_name=normalized_name,
                    prompt_candidates=prompt_candidates,
                    selected_prompt=prompt,
                    attempt_count=attempt_count,
                )

            return SAM3PreprocessOutcome(
                result_image=None,
                original_item_name=item_name,
                normalized_item_name=normalized_name,
                prompt_candidates=prompt_candidates,
                selected_prompt=None,
                attempt_count=attempt_count,
            )
        except Exception as e:
            logger.error(f"SAM3 preprocessing failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return SAM3PreprocessOutcome(
                result_image=None,
                original_item_name=item_name,
                normalized_item_name=normalized_name,
                prompt_candidates=prompt_candidates,
                selected_prompt=None,
                attempt_count=attempt_count,
            )

    def preprocess_image(
        self,
        image: Image.Image,
        item_name: str,
        image_id: Optional[int] = None
    ) -> Optional[Image.Image]:
        """
        预处理图像：SAM3 分割 + 背景替换

        Args:
            image: 输入图像
            item_name: 零件名称（用于提取提示词）
            image_id: 图像ID（用于保存调试图像）

        Returns:
            处理后的图像，如果失败返回 None
        """
        return self.preprocess_image_with_metadata(
            image=image,
            item_name=item_name,
            image_id=image_id,
        ).result_image

    def _save_debug_images(
        self,
        original: Image.Image,
        mask: np.ndarray,
        result: Image.Image,
        image_id: int,
        item_name: str,
        text_prompt: str,
        normalized_item_name: Optional[str] = None,
        prompt_candidates: Optional[list[str]] = None,
        selected_prompt: Optional[str] = None,
        prompt_attempt_count: Optional[int] = None,
        index_strategy: Optional[str] = None,
    ):
        """保存调试图像"""
        try:
            import cv2
            
            # 创建子目录
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            debug_dir = os.path.join(self.debug_output_dir, f"{image_id}_{timestamp}")
            os.makedirs(debug_dir, exist_ok=True)

            # 保存原图
            original.save(os.path.join(debug_dir, "1_original.jpg"))

            # 保存 mask
            mask_img = (mask * 255).astype(np.uint8)
            cv2.imwrite(os.path.join(debug_dir, "2_mask.jpg"), mask_img)

            # 保存结果
            result.save(os.path.join(debug_dir, "3_result.jpg"))

            # 保存信息文件
            info_path = os.path.join(debug_dir, "info.txt")
            with open(info_path, 'w', encoding='utf-8') as f:
                f.write(f"Image ID: {image_id}\n")
                f.write(f"Item Name: {item_name}\n")
                if normalized_item_name is not None:
                    f.write(f"Normalized Item Name: {normalized_item_name}\n")
                f.write(f"Text Prompt: {text_prompt}\n")
                if prompt_candidates is not None:
                    f.write(f"Prompt Candidates: {prompt_candidates}\n")
                if selected_prompt is not None:
                    f.write(f"Selected Prompt: {selected_prompt}\n")
                if prompt_attempt_count is not None:
                    f.write(f"Prompt Attempt Count: {prompt_attempt_count}\n")
                if index_strategy is not None:
                    f.write(f"Index Strategy: {index_strategy}\n")
                f.write(f"Original Size: {original.size}\n")
                f.write(f"Result Size: {result.size}\n")
                f.write(f"Mask Dilate: {self.mask_dilate}\n")
                f.write(f"BG Color: {self.bg_color}\n")

            logger.info(f"Debug images saved to: {debug_dir}")

        except Exception as e:
            logger.warning(f"Failed to save debug images: {e}")
