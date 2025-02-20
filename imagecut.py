import os
from PIL import Image
import cv2
import numpy as np
from pathlib import Path

class MediaProcessor:
    def __init__(self, input_dir, output_dir, target_size=(300, 300)):
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.target_size = target_size
        # 加载人脸检测器
        self.face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        
        # 支持的文件格式
        self.image_extensions = {'.jpg', '.jpeg', '.png', '.webp'}
        self.video_extensions = {'.mp4', '.mov', '.avi'}

    def process_directory(self):
        """处理目录中的所有媒体文件"""
        for file_path in self.input_dir.rglob('*'):
            if file_path.suffix.lower() in self.image_extensions:
                self.process_image(file_path)
            elif file_path.suffix.lower() in self.video_extensions:
                self.process_video(file_path)

    def smart_crop(self, image):
        """智能裁剪，保持主体在中间且完整"""
        width, height = image.size
        
        if width == height:
            return image
            
        # 转换为numpy数组和OpenCV格式
        img_array = np.array(image)
        if len(img_array.shape) == 3:
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        
        # 使用Canny边缘检测找到主体
        edges = cv2.Canny(gray, 100, 200)
        
        # 找到所有非零点（边缘点）
        points = np.where(edges != 0)
        
        if len(points[0]) > 0:
            # 获取主体区域的边界
            min_y, max_y = np.min(points[0]), np.max(points[0])
            min_x, max_x = np.min(points[1]), np.max(points[1])
            
            # 计算主体的中心
            center_x = (min_x + max_x) // 2
            center_y = (min_y + max_y) // 2
            
            # 计算主体的宽度和高度
            subject_width = max_x - min_x
            subject_height = max_y - min_y
            
            # 确定正方形裁剪区域的大小
            # 使用主体高度的1.2倍作为最小尺寸，确保主体完整显示
            crop_size = max(int(subject_height * 1.2), int(subject_width * 1.2))
            crop_size = max(crop_size, min(width, height))  # 确保至少和短边一样长
            
            # 计算裁剪区域，保持主体在中心
            left = center_x - crop_size // 2
            top = center_y - crop_size // 2
            
            # 创建一个新的白色背景图像
            new_img = Image.new('RGB', (crop_size, crop_size), (255, 255, 255))
            
            # 调整裁剪区域，确保不超出原图范围
            effective_left = max(0, left)
            effective_top = max(0, top)
            effective_right = min(width, left + crop_size)
            effective_bottom = min(height, top + crop_size)
            
            # 计算在新图像中的粘贴位置
            paste_left = max(0, -left)
            paste_top = max(0, -top)
            
            # 复制原图像的部分到新图像
            region = image.crop((effective_left, effective_top, effective_right, effective_bottom))
            new_img.paste(region, (paste_left, paste_top))
            
            return new_img
        else:
            # 如果没有检测到明显的边缘，使用中心裁剪
            crop_size = min(width, height)
            left = (width - crop_size) // 2
            top = (height - crop_size) // 2
            
            # 创建一个新的白色背景图像
            new_img = Image.new('RGB', (crop_size, crop_size), (255, 255, 255))
            
            # 裁剪并粘贴中心区域
            region = image.crop((left, top, left + crop_size, top + crop_size))
            new_img.paste(region, (0, 0))
            
            return new_img

    def process_image(self, image_path):
        """处理单个图片"""
        try:
            with Image.open(image_path) as img:
                img = img.convert('RGB')
                
                # 智能裁剪
                cropped_img = self.smart_crop(img)
                
                # 调整大小
                thumbnail = cropped_img.resize(self.target_size, Image.Resampling.LANCZOS)
                
                # 在原目录保存缩略图
                output_path = image_path.parent / f"thumb_{image_path.name}"
                thumbnail.save(output_path, "JPEG", quality=85)
                print(f"已处理图片: {image_path.name}")
        except Exception as e:
            print(f"处理图片 {image_path.name} 时出错: {str(e)}")

    def process_video(self, video_path):
        """处理单个视频"""
        try:
            cap = cv2.VideoCapture(str(video_path))
            
            # 获取视频总帧数
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            
            # 设置到中间帧的位置
            middle_frame = total_frames // 2
            cap.set(cv2.CAP_PROP_POS_FRAMES, middle_frame)
            
            # 读取中间帧
            ret, frame = cap.read()
            
            if ret:
                # 转换为PIL图像
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(frame_rgb)
                
                # 智能裁剪
                cropped_img = self.smart_crop(img)
                
                # 调整大小
                thumbnail = cropped_img.resize(self.target_size, Image.Resampling.LANCZOS)
                
                # 在原目录保存缩略图
                output_path = video_path.parent / f"thumb_{video_path.stem}.jpg"
                thumbnail.save(output_path, "JPEG", quality=85)
                print(f"已处理视频: {video_path.name}")
            
            cap.release()
        except Exception as e:
            print(f"处理视频 {video_path.name} 时出错: {str(e)}")

if __name__ == "__main__":
    # 使用示例
    processor = MediaProcessor(
        input_dir="strong",  # 输入目录改为 D
        output_dir="strong",  # 输出目录也是 D
        target_size=(64, 64)  # 目标缩略图尺寸
    )
    processor.process_directory()
