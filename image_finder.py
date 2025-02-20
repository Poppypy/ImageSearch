from PIL import Image, ImageGrab
import imagehash
from pathlib import Path
import sys
import shutil
import os
from datetime import datetime

def get_image_hash(image_path):
    """计算图片的感知哈希值"""
    try:
        with Image.open(image_path) as img:
            # 将图片转换为RGB模式
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # 获取图片尺寸
            width, height = img.size
            is_thumbnail = width <= 300 or height <= 300
            
            if is_thumbnail:
                # 对于缩略图，使用更小的目标尺寸
                target_size = (32, 32)
            else:
                # 对于普通图片，使用较大的目标尺寸
                target_size = (64, 64)
                
            # 调整图片大小
            img = img.resize(target_size, Image.Resampling.LANCZOS)
            
            # 使用多种哈希算法组合
            avg_hash = imagehash.average_hash(img)
            dhash = imagehash.dhash(img)  # 对边缘更敏感
            whash = imagehash.whash(img)  # 小波变换哈希，对细节更敏感
            
            return (avg_hash, dhash, whash, is_thumbnail)
    except Exception as e:
        print(f"处理图片 {image_path} 时出错: {e}")
        return None

def get_clipboard_image_hash():
    """获取剪贴板图片的哈希值"""
    try:
        clipboard_image = ImageGrab.grabclipboard()
        if clipboard_image is None:
            print("剪贴板中没有图片")
            return None
            
        # 将图片转换为RGB模式
        if clipboard_image.mode != 'RGB':
            clipboard_image = clipboard_image.convert('RGB')
            
        # 获取图片尺寸
        width, height = clipboard_image.size
        is_thumbnail = width <= 300 or height <= 300
        
        if is_thumbnail:
            target_size = (32, 32)
        else:
            target_size = (64, 64)
            
        clipboard_image = clipboard_image.resize(target_size, Image.Resampling.LANCZOS)
        
        # 使用多种哈希算法
        avg_hash = imagehash.average_hash(clipboard_image)
        dhash = imagehash.dhash(clipboard_image)
        whash = imagehash.whash(clipboard_image)
        
        return (avg_hash, dhash, whash, is_thumbnail)
    except Exception as e:
        print(f"获取剪贴板图片时出错: {e}")
        return None

def copy_similar_images(similar_images, base_dir="."):
    """将相似图片复制到指定目录"""
    # 创建保存相似图片的目录
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    similar_dir = Path(base_dir) / f"similar_images_{timestamp}"
    similar_dir.mkdir(exist_ok=True)
    
    # 复制文件并保持原始文件名
    copied_files = []
    for path, _, is_thumb in similar_images:
        try:
            # 获取原始文件名
            original_name = path.name
            # 构建目标路径
            dest_path = similar_dir / original_name
            
            # 如果文件名已存在，添加数字后缀
            counter = 1
            while dest_path.exists():
                name_parts = os.path.splitext(original_name)
                dest_path = similar_dir / f"{name_parts[0]}_{counter}{name_parts[1]}"
                counter += 1
            
            # 复制文件
            shutil.copy2(path, dest_path)
            copied_files.append(dest_path)
            print(f"已复制: {path} -> {dest_path}")
        except Exception as e:
            print(f"复制文件 {path} 时出错: {e}")
    
    return similar_dir, copied_files

def find_similar_images(directory, threshold=12):
    """查找与剪贴板图片相似的图片"""
    clipboard_hashes = get_clipboard_image_hash()
    if clipboard_hashes is None:
        return

    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
    directory_path = Path(directory)
    similar_images = []
    
    clipboard_is_thumbnail = clipboard_hashes[3]
    
    for image_path in directory_path.rglob('*'):
        if image_path.suffix.lower() in image_extensions:
            img_hashes = get_image_hash(image_path)
            if img_hashes is not None:
                img_is_thumbnail = img_hashes[3]
                
                # 根据是否为缩略图调整权重
                if clipboard_is_thumbnail == img_is_thumbnail:
                    weight_avg = 0.4
                    weight_dhash = 0.3
                    weight_whash = 0.3
                else:
                    # 如果一个是缩略图一个不是，调整权重
                    weight_avg = 0.3
                    weight_dhash = 0.4
                    weight_whash = 0.3
                
                # 计算加权平均差异
                avg_diff = clipboard_hashes[0] - img_hashes[0]
                dhash_diff = clipboard_hashes[1] - img_hashes[1]
                whash_diff = clipboard_hashes[2] - img_hashes[2]
                
                total_diff = (avg_diff * weight_avg + 
                            dhash_diff * weight_dhash + 
                            whash_diff * weight_whash)
                
                if total_diff < threshold:
                    similar_images.append((image_path, total_diff, img_is_thumbnail))
    
    # 按相似度排序
    similar_images.sort(key=lambda x: x[1])
    
    # 显示结果
    if similar_images:
        print("\n找到以下相似图片:")
        filtered_images = []
        for path, diff, is_thumb in similar_images:
            similarity = 100 - (diff/64*100)
            if similarity > 25:  # 降低相似度阈值
                thumb_mark = "[缩略图]" if is_thumb else ""
                print(f"相似度: {similarity:.2f}% {thumb_mark} - {path}")
                filtered_images.append((path, diff, is_thumb))
        
        # 复制相似图片
        if filtered_images:
            similar_dir, copied_files = copy_similar_images(filtered_images)
            print(f"\n所有相似图片已复制到: {similar_dir}")
            print(f"共复制了 {len(copied_files)} 个文件")
    else:
        print("没有找到相似的图片")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        directory = sys.argv[1]
    else:
        directory = "."  # 默认为当前目录
    
    print("正在搜索相似图片...")
    find_similar_images(directory) 