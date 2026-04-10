"""
DINOv2 向量提取器（独立版）
"""
import os
import torch
import numpy as np
from PIL import Image
from typing import Tuple
from transformers import AutoImageProcessor, AutoModel

from csrcqsf.biz.railwayparts.vector_db.utils.logger import setup_logger

logger = setup_logger(__name__)


class DINOv2VectorExtractor:
    """
    DINOv2 向量提取器
    用于向量库的特征提取
    """
    
    def __init__(self, model_name: str = "facebook/dinov2-large", device: str = "cuda"):
        """
        初始化 DINOv2 提取器
        
        Args:
            model_name: HuggingFace 模型名称或本地路径
            device: 设备 ('cuda' 或 'cpu')
        """
        self.device = device if torch.cuda.is_available() else "cpu"
        self.model_name = model_name
        
        logger.info(f"Loading DINOv2 model: {model_name}")
        self.processor = AutoImageProcessor.from_pretrained(model_name)
        self.model = AutoModel.from_pretrained(model_name)
        self.model.to(self.device)
        self.model.eval()
        
        logger.info(f"DINOv2 loaded successfully on {self.device}")

    def extract_global_vector(self, image: Image.Image) -> np.ndarray:
        """
        提取全局特征向量（CLS token）

        Args:
            image: PIL Image 对象

        Returns:
            全局特征向量 (1024,)
        """
        inputs = self.processor(images=image, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self.model(**inputs)

        # 提取 CLS token
        cls_token = outputs.last_hidden_state[:, 0, :].cpu().numpy()[0]

        return cls_token

    def extract_patch_tokens(self, image: Image.Image) -> np.ndarray:
        """
        提取完整 Patch Tokens

        Args:
            image: PIL Image 对象

        Returns:
            Patch Tokens 矩阵 (1369, 1024)
        """
        inputs = self.processor(images=image, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        # 计算 patch 数量
        actual_h = inputs["pixel_values"].shape[2]
        actual_w = inputs["pixel_values"].shape[3]
        patch_size = 14
        h, w = actual_h // patch_size, actual_w // patch_size

        with torch.no_grad():
            outputs = self.model(**inputs)

        # 提取 patch tokens（跳过 CLS token）
        patch_tokens = outputs.last_hidden_state[:, 1:1 + h * w, :].cpu().numpy()[0]

        return patch_tokens

    def extract_patch_mean(self, image: Image.Image) -> np.ndarray:
        """
        提取 Patch Tokens 的均值向量

        Args:
            image: PIL Image 对象

        Returns:
            Patch Tokens 均值向量 (1024,)
        """
        patch_tokens = self.extract_patch_tokens(image)
        patch_mean = np.mean(patch_tokens, axis=0)

        return patch_mean

    def save_patch_tokens(self, patch_tokens: np.ndarray, save_path: str):
        """
        保存 Patch Tokens 到 .npy 文件

        Args:
            patch_tokens: Patch Tokens 矩阵
            save_path: 保存路径
        """
        # 创建目录
        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        # 保存为 .npy 文件
        np.save(save_path, patch_tokens)
        logger.debug(f"Saved patch tokens to: {save_path}")

    def extract_all_features(
        self,
        image: Image.Image,
        patch_tokens_path: str
    ) -> Tuple[np.ndarray, np.ndarray, str]:
        """
        提取所有特征并保存 Patch Tokens

        Args:
            image: PIL Image 对象
            patch_tokens_path: Patch Tokens 保存路径

        Returns:
            (global_vector, patch_mean, patch_tokens_path)
        """
        # 提取全局向量
        global_vector = self.extract_global_vector(image)

        # 提取 Patch Tokens
        patch_tokens = self.extract_patch_tokens(image)

        # 计算 Patch Tokens 均值
        patch_mean = np.mean(patch_tokens, axis=0)

        # 保存 Patch Tokens
        self.save_patch_tokens(patch_tokens, patch_tokens_path)

        return global_vector, patch_mean, patch_tokens_path
