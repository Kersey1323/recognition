import torch
import torch.nn.functional as F
from diff_gaussian_rasterization import GaussianRasterizer
from scene import Scene, GaussianModel

def train_2dgs_core_loop(dataset, iterations=30000):
    """
    2DGS 可微渲染训练核心代码骨架 (对应流程图 第二阶段: 2DGS可微渲染训练)
    """
    # 1. 初始化 2DGS 模型 (对应: INIT_2DGS[2D高斯体云初始化])
    gaussians = GaussianModel(sh_degree=3)
    scene = Scene(dataset, gaussians)
    
    # 获取所有的训练视角相机参数
    viewpoints = scene.getTrainCameras()
    
    # 优化器设置
    optimizer = gaussians.setup_optimizer()
    
    for iteration in range(1, iterations + 1):
        # 随机抽取一个相机视角
        viewpoint_cam = viewpoints[torch.randint(0, len(viewpoints), (1,)).item()]
        
        # 将3D属性“拍扁”，抽取构建 2D 法线
        # 我们不再优化完整的 3D 缩放，而是优化两根主要的2D缩放轴，第三根强制非常小
        normals = gaussians.get_normals()

        # 2. 前向光栅化体积渲染 (对应: T_FORWARD[前向光栅化渲染])
        # render_pkg 将输出: 渲染的图像(image), 渲染的深度图(depth), 渲染的法向量图(rend_normal)
        render_pkg = render_2dgs(viewpoint_cam, gaussians, pipeline_settings)
        image, depth, rend_normal = render_pkg["render"], render_pkg["depth"], render_pkg["normal"]
        
        # 提取真实世界图像参考 (Ground Truth)
        gt_image = viewpoint_cam.original_image.cuda()
        
        # -------------------------------------------------------------
        # 3. 核心机制：Loss评估提取与正则化 (对应: T_LOSS 和 T_REGULAR)
        # -------------------------------------------------------------
        
        # 3A: 基础光度学损失 (L1 Loss + D-SSIM)
        Ll1 = l1_loss(image, gt_image)
        # 保证 SSIM 也向着原图收敛
        loss_color = (1.0 - lambda_dssim) * Ll1 + lambda_dssim * (1.0 - ssim(image, gt_image))
        
        # 3B: 2DGS的精髓 —— 深度一致性与法向量正则化 (Depth & Normal Consistency)
        # 强制高斯面片的法方向与光学像素深度梯度产生的几何面完全垂直对齐
        
        # 从渲染深度图中计算出的屏幕空间梯度法向 (伪代码计算深度梯度)
        pseudo_normal_from_depth = depth_to_normal(viewpoint_cam, depth) 
        
        # [核心正则化方程]: 光栅化出来的原生法向 必须向 计算出来的几何深度法向 贴合
        loss_normal = (1 - (pseudo_normal_from_depth * rend_normal).sum(dim=0)).mean()
        
        # 综合考虑约束
        total_loss = loss_color + lambda_normal * loss_normal
        

        # 4. 反向传播求导 (对应: T_BACK[反向传播求导])
        total_loss.backward()

        # 5. 更新与自适应控制 (对应: T_UPDATE 和 T_CLONE)
        with torch.no_grad():
            # 更新 高斯面片的: 坐标, SH(颜色), 2D缩放, 旋转四元数, 不透明度
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
            
            # 自适应密度管控: 抹除低透明度的废点，在梯度大的区域克隆(Clone)/分裂(Split)新的高斯面片
            if iteration < densify_until_iter:
                gaussians.densify_and_prune(max_grad, min_opacity, extent, max_screen_size)
                
    # 训练完成
    return gaussians
