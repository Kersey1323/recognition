export:
    uv run export_onnx_model.py --checkpoint /opt/models/sam_vit_h_4b8939.pth --model-type vit_h --output onnx_vit_h.onnx --return-single-mask

embedding_models:
    modelscope download --model AI-ModelScope/bge-small-zh-v1.5 --local_dir ./embedding_models

resnet_models:
    huggingface-cli download --resume-download timm/resnet34.a1_in1k --local-dir ./resnet --local-dir-use-symlinks False

# 从视频中抽取 100-150 张图片用于 3D 重建
# 用法: just extract-frames <视频文件> <输出目录> [目标帧数]
# 示例: just extract-frames video.mp4 ./images 120
extract-frames video output_dir frames="120":
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p {{output_dir}}
    # 获取视频总帧数
    total_frames=$(ffprobe -v error -select_streams v:0 -count_packets -show_entries stream=nb_read_packets -of csv=p=0 "{{video}}")
    # 计算采样间隔
    interval=$((total_frames / {{frames}}))
    if [ $interval -lt 1 ]; then interval=1; fi
    echo "视频总帧数: $total_frames, 采样间隔: $interval, 目标帧数: {{frames}}"
    # 使用 select 过滤器均匀采样
    ffmpeg -i "{{video}}" -vf "select='not(mod(n\,${interval}))',setpts=N/FRAME_RATE/TB" -vsync vfr -q:v 2 "{{output_dir}}/frame_%04d.jpg"
    echo "完成! 图片保存到: {{output_dir}}"

# 简化版: 按固定帧率抽帧 (推荐用于短视频)
# 用法: just extract-fps <视频文件> <输出目录> [fps]
extract-fps video output_dir fps="2":
    mkdir -p {{output_dir}}
    ffmpeg -i "{{video}}" -vf "fps={{fps}}" -q:v 2 "{{output_dir}}/frame_%04d.jpg"
    echo "完成! 图片保存到: {{output_dir}}"

# 合并多个视频文件
# 用法: just concat-videos <输出文件> <视频1> <视频2> ...
# 示例: just concat-videos output.mp4 video1.mp4 video2.mp4 video3.mp4
concat-videos output +videos:
    #!/usr/bin/env bash
    set -euo pipefail
    # 创建临时文件列表
    filelist=$(mktemp)
    trap "rm -f $filelist" EXIT
    for v in {{videos}}; do
        echo "file '$(realpath "$v")'" >> "$filelist"
    done
    echo "合并以下视频:"
    cat "$filelist"
    # 使用 concat demuxer 合并 (无需重新编码)
    ffmpeg -f concat -safe 0 -i "$filelist" -c copy "{{output}}"
    echo "完成! 输出文件: {{output}}"

# 合并目录下所有视频 (按文件名排序)
# 用法: just concat-dir <视频目录> <输出文件> [扩展名]
# 示例: just concat-dir ./videos output.mp4 mp4
concat-dir video_dir output ext="mp4":
    #!/usr/bin/env bash
    set -euo pipefail
    filelist=$(mktemp)
    trap "rm -f $filelist" EXIT
    # 查找并排序所有视频文件
    find "{{video_dir}}" -maxdepth 1 -name "*.{{ext}}" | sort | while read f; do
        echo "file '$(realpath "$f")'" >> "$filelist"
    done
    count=$(wc -l < "$filelist")
    echo "找到 $count 个 .{{ext}} 文件"
    cat "$filelist"
    ffmpeg -f concat -safe 0 -i "$filelist" -c copy "{{output}}"
    echo "完成! 输出文件: {{output}}"

# 合并视频并统一编码 (不同格式/分辨率时使用)
# 用法: just concat-reencode <输出文件> <视频1> <视频2> ...
concat-reencode output +videos:
    #!/usr/bin/env bash
    set -euo pipefail
    inputs=""
    filter=""
    i=0
    for v in {{videos}}; do
        inputs="$inputs -i \"$v\""
        filter="${filter}[$i:v][$i:a]"
        i=$((i+1))
    done
    filter="${filter}concat=n=$i:v=1:a=1[v][a]"
    eval ffmpeg $inputs -filter_complex "'$filter'" -map "'[v]'" -map "'[a]'" -c:v libx264 -crf 23 -c:a aac "{{output}}"
    echo "完成! 输出文件: {{output}}"