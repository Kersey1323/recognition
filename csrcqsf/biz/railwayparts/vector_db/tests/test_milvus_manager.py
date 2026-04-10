#!/usr/bin/env python3
"""
测试 MilvusManager 统一管理器
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from PIL import Image
from vector_db.storage.milvus_manager import MilvusManager
from vector_db.utils.logger import setup_logger

logger = setup_logger(__name__)


def test_text_search(manager: MilvusManager):
    """测试文本检索"""
    print("\n" + "="*80)
    print("Testing Text Search (SigLIP)")
    print("="*80)

    query_text = "特殊螺栓"
    results = manager.search_by_text(query_text, top_k=5)

    print(f"\nQuery: {query_text}")
    print(f"Found {len(results)} results:\n")

    for i, result in enumerate(results, 1):
        print(f"Rank {i}:")
        print(f"  Score: {result['distance']:.4f}")
        print(f"  Item: {result['entity']['item_name']} ({result['entity']['item_code']})")
        print(f"  Image ID: {result['entity']['image_id']}")
        print()


def test_image_search(manager: MilvusManager, query_image_path: str, mode: str = "hybrid"):
    """测试图像检索"""
    print("\n" + "="*80)
    print(f"Testing Image Search (Mode: {mode})")
    print("="*80)

    results = manager.search_by_image(
        query_image_path,
        top_k=5,
        mode=mode
    )

    print(f"\nQuery Image: {query_image_path}")
    print(f"Found {len(results)} results:\n")

    for i, result in enumerate(results, 1):
        print(f"Rank {i}:")
        if 'final_score' in result:
            print(f"  Final Score: {result['final_score']:.4f}")
            print(f"    ├─ RRF Score: {result.get('rrf_score', 0):.4f}")
            print(f"    └─ Patch Score: {result.get('patch_score', 0):.4f}")
        else:
            print(f"  Score: {result['distance']:.4f}")
        print(f"  Item: {result['entity']['item_name']} ({result['entity']['item_code']})")
        print(f"  Image ID: {result['entity']['image_id']}")
        print()


def main():
    """主测试函数"""
    import argparse

    parser = argparse.ArgumentParser(description="Test MilvusManager")
    parser.add_argument('--mode', type=str, choices=['text', 'image'], required=True,
                        help='Search mode: text or image')
    parser.add_argument('--query', type=str, required=True,
                        help='Query text or image path')
    parser.add_argument('--image-mode', type=str, choices=['siglip', 'dinov2', 'hybrid'],
                        default='hybrid', help='Image search mode (default: hybrid)')
    parser.add_argument('--top-k', type=int, default=5,
                        help='Number of results to return')
    args = parser.parse_args()

    # 初始化管理器
    logger.info("Initializing MilvusManager...")
    manager = MilvusManager()

    # 执行测试
    if args.mode == 'text':
        test_text_search(manager)
    else:
        test_image_search(manager, args.query, mode=args.image_mode)

    print("\n✓ Test completed!")


if __name__ == "__main__":
    main()
