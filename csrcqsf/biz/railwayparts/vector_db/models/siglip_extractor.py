"""
SigLIP 2 特征提取器
"""
import torch
import numpy as np
from PIL import Image
from typing import List, Union
from transformers import AutoModel, AutoProcessor

from csrcqsf.biz.railwayparts.vector_db.utils.logger import setup_logger

logger = setup_logger(__name__)


class SigLIPExtractor:
    """SigLIP 2 特征提取器"""

    def __init__(self, model_path: str, device: str = "cuda"):
        """
        初始化 SigLIP 2 模型

        Args:
            model_path: 模型路径
            device: 设备 ('cuda' 或 'cpu')
        """
        self.device = device if torch.cuda.is_available() else "cpu"
        logger.info(f"Loading SigLIP model from: {model_path}")

        # 确保 model_path 是字符串
        model_path = str(model_path)

        # 使用 AutoProcessor 统一加载（包含 image processor 和 tokenizer）
        self.processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True)
        self.model = AutoModel.from_pretrained(model_path, trust_remote_code=True)
        
        self.model.to(self.device)
        self.model.eval()

        logger.info(f"SigLIP model loaded successfully on {self.device}")

    def extract_image_features(self, image: Image.Image) -> np.ndarray:
        """
        提取图像特征向量

        Args:
            image: PIL Image 对象

        Returns:
            归一化的图像特征向量 (1152,)
        """
        inputs = self.processor(images=image, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self.model.get_image_features(**inputs)
            # Handle both tensor and ModelOutput types
            if isinstance(outputs, torch.Tensor):
                image_features = outputs
            else:
                # For BaseModelOutputWithPooling, use pooler_output (CLS token)
                if hasattr(outputs, 'pooler_output') and outputs.pooler_output is not None:
                    image_features = outputs.pooler_output
                else:
                    # Fallback: take CLS token from last_hidden_state
                    image_features = outputs.last_hidden_state[:, 0]

        # L2 归一化 - ensure we get 1D vector
        features = image_features.cpu().numpy()
        # Handle different output shapes
        if features.ndim > 1:
            if features.shape[0] == 1:
                # Shape (1, dim) -> take first row
                features = features[0]
            else:
                # Shape (batch, dim) -> take mean pooling to get single vector
                features = features.mean(axis=0)
        features = features / np.linalg.norm(features)

        return features

    def extract_text_features(self, text: str) -> np.ndarray:
        """
        提取文本特征向量

        Args:
            text: 文本描述

        Returns:
            归一化的文本特征向量 (1152,)
        """
        inputs = self.processor(text=text, return_tensors="pt", padding=True)
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self.model.get_text_features(**inputs)
            # Handle both tensor and ModelOutput types
            if isinstance(outputs, torch.Tensor):
                text_features = outputs
            else:
                # For BaseModelOutputWithPooling, use pooler_output (CLS token)
                if hasattr(outputs, 'pooler_output') and outputs.pooler_output is not None:
                    text_features = outputs.pooler_output
                else:
                    # Fallback: take CLS token from last_hidden_state
                    text_features = outputs.last_hidden_state[:, 0]

        # L2 归一化 - ensure we get 1D vector
        features = text_features.cpu().numpy()
        # Handle different output shapes
        if features.ndim > 1:
            if features.shape[0] == 1:
                # Shape (1, dim) -> take first row
                features = features[0]
            else:
                # Shape (batch, dim) -> take mean pooling
                features = features.mean(axis=0)
        features = features / np.linalg.norm(features)

        return features

    def extract_batch_images(self, images: List[Image.Image]) -> np.ndarray:
        """
        批量提取图像特征

        Args:
            images: PIL Image 对象列表

        Returns:
            归一化的图像特征矩阵 (N, 1152)
        """
        inputs = self.processor(images=images, return_tensors="pt", padding=True)
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self.model.get_image_features(**inputs)
            # Handle both tensor and ModelOutput types
            if isinstance(outputs, torch.Tensor):
                image_features = outputs
            else:
                # For BaseModelOutputWithPooling or similar
                image_features = outputs[0] if hasattr(outputs, '__getitem__') else outputs.pooler_output

        # L2 归一化
        features = image_features.cpu().numpy()
        features = features / np.linalg.norm(features, axis=1, keepdims=True)

        return features
