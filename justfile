export:
    uv run export_onnx_model.py --checkpoint /opt/models/sam_vit_h_4b8939.pth --model-type vit_h --output onnx_vit_h.onnx --return-single-mask

embedding_models:
    modelscope download --model AI-ModelScope/bge-small-zh-v1.5 --local_dir ./embedding_models

resnet_models:
    huggingface-cli download --resume-download timm/resnet34.a1_in1k --local-dir ./resnet --local-dir-use-symlinks False