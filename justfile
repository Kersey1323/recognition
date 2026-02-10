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
    #!powershell
    New-Item -ItemType Directory -Force -Path "{{output_dir}}" | Out-Null
    $total = (ffprobe -v error -select_streams v:0 -count_packets -show_entries stream=nb_read_packets -of csv=p=0 "{{video}}")
    $interval = [math]::Max(1, [math]::Floor($total / {{frames}}))
    Write-Host "视频总帧数: $total, 采样间隔: $interval, 目标帧数: {{frames}}"
    ffmpeg -i "{{video}}" -vf "select='not(mod(n,$interval))',setpts=N/FRAME_RATE/TB" -vsync vfr -q:v 2 "{{output_dir}}/frame_%04d.jpg"
    Write-Host "完成! 图片保存到: {{output_dir}}"

# 简化版: 按固定帧率抽帧 (推荐用于短视频)
# 用法: just extract-fps <视频文件> <输出目录> [fps]
extract-fps video output_dir fps="2":
    #!powershell
    New-Item -ItemType Directory -Force -Path "{{output_dir}}" | Out-Null
    ffmpeg -i "{{video}}" -vf "fps={{fps}}" -q:v 2 "{{output_dir}}/frame_%04d.jpg"
    Write-Host "完成! 图片保存到: {{output_dir}}"

# 合并多个视频文件 (相同编码格式)
# 用法: just concat-videos <输出文件> <视频1> <视频2> ...
# 示例: just concat-videos output.mp4 video1.mp4 video2.mp4 video3.mp4
concat-videos output +videos:
    #!powershell
    $filelist = "filelist_temp.txt"
    $videos = "{{videos}}" -split ' '
    $videos | ForEach-Object { "file '$((Resolve-Path $_).Path -replace '\\','/')'" } | Out-File -Encoding utf8 $filelist
    Write-Host "合并以下视频:"
    Get-Content $filelist
    ffmpeg -f concat -safe 0 -i $filelist -c copy "{{output}}"
    Remove-Item $filelist
    Write-Host "完成! 输出文件: {{output}}"

# 合并目录下所有视频 (按文件名排序)
# 用法: just concat-dir <视频目录> <输出文件> [扩展名]
# 示例: just concat-dir ./videos output.mp4 mp4
concat-dir video_dir output ext="mp4":
    #!powershell
    $filelist = "filelist_temp.txt"
    $files = Get-ChildItem -Path "{{video_dir}}" -Filter "*.{{ext}}" | Sort-Object Name
    $files | ForEach-Object { "file '$($_.FullName -replace '\\','/')'" } | Out-File -Encoding utf8 $filelist
    Write-Host "找到 $($files.Count) 个 .{{ext}} 文件"
    Get-Content $filelist
    ffmpeg -f concat -safe 0 -i $filelist -c copy "{{output}}"
    Remove-Item $filelist
    Write-Host "完成! 输出文件: {{output}}"

# 合并视频并重新编码 (不同格式/分辨率时使用)
# 用法: just concat-reencode <输出文件> <视频1> <视频2> ...
concat-reencode output +videos:
    #!powershell
    $videos = "{{videos}}" -split ' '
    $inputs = ($videos | ForEach-Object { "-i `"$_`"" }) -join ' '
    $n = $videos.Count
    $streams = (0..($n-1) | ForEach-Object { "[$_`:v][$_`:a]" }) -join ''
    $filter = "${streams}concat=n=${n}:v=1:a=1[v][a]"
    $cmd = "ffmpeg $inputs -filter_complex `"$filter`" -map `"[v]`" -map `"[a]`" -c:v libx264 -crf 23 -c:a aac `"{{output}}`""
    Write-Host "执行: $cmd"
    Invoke-Expression $cmd
    Write-Host "完成! 输出文件: {{output}}"