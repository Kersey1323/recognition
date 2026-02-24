"""测试 MaskPreprocessor 前景提取效果

从 images/ 读取照片，提取公共主体 (背景→白色)，
结果保存到 output/masked_images/
"""

from csrcqsf.biz.reconstruction.mask_preprocessor import MaskPreprocessor

INPUT_DIR = "./images"
OUTPUT_DIR = "./output/masked_images"

if __name__ == "__main__":
    print(f"输入目录: {INPUT_DIR}")
    print(f"输出目录: {OUTPUT_DIR}")
    print("=" * 40)
    
    result = MaskPreprocessor.preprocess_images(
        input_dir=INPUT_DIR,
        output_dir=OUTPUT_DIR,
    )
    
    print("=" * 40)
    print(f"总计: {result['total']} 张")
    print(f"成功: {result['masked']} 张")
    print(f"跳过: {result['skipped']} 张")
    print(f"结果: {'✅ 成功' if result['success'] else '❌ 失败'}")
    
    if result.get('suspicious'):
        print(f"\n⚠️  发现 {len(result['suspicious'])} 张可疑分割:")
        for s in result['suspicious']:
            print(f"  - {s['file']}: {s['ratio']:.1%} ({s['reason']}, 中位数 {s['median']:.1%})")
    else:
        print("\n✅ 异常检测通过，所有 mask 面积正常")
    
    print(f"\n输出目录: {OUTPUT_DIR}")
