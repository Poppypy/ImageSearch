import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext
from PIL import Image, ImageGrab, ImageTk
import imagehash
from pathlib import Path
import sys
import shutil
import os
from datetime import datetime
import threading
import io
from image_finder import get_image_hash, get_clipboard_image_hash, copy_similar_images
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import asyncio
import aiofiles
from io import BytesIO
import queue
import win32clipboard

class ScrollableFrame(ttk.Frame):
    def __init__(self, container, *args, **kwargs):
        super().__init__(container, *args, **kwargs)
        canvas = tk.Canvas(self)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

class ImageFinderGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("图片相似度查找器")
        self.root.geometry("800x600")
        
        # 设置窗口图标
        try:
            self.root.iconbitmap("app.ico")  # 确保app.ico在同一目录下
        except Exception:
            pass  # 如果图标加载失败，使用默认图标
        
        # 创建菜单栏
        self.menubar = tk.Menu(root)
        root.config(menu=self.menubar)
        
        # 创建帮助菜单
        self.help_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="帮助", menu=self.help_menu)
        self.help_menu.add_command(label="关于", command=self.show_about)
        
        # 初始化控制变量
        self.preview_enabled = True
        self.threshold_timer = None
        self.photo_cache = {}
        self.all_similar_images = []
        self.current_search_image = None
        self.image_labels = []
        self.load_queue = queue.Queue()
        self.is_loading = False
        self.executor = ThreadPoolExecutor(max_workers=4)
        
        # 创建主框架
        self.main_frame = ttk.Frame(root, padding="10")
        self.main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 创建上部控制区域
        self.control_frame = ttk.LabelFrame(self.main_frame, text="控制面板", padding="5")
        self.control_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        # 目录选择
        self.dir_label = ttk.Label(self.control_frame, text="搜索目录:")
        self.dir_label.grid(row=0, column=0, padx=5)
        
        self.dir_var = tk.StringVar(value=os.getcwd())
        self.dir_entry = ttk.Entry(self.control_frame, textvariable=self.dir_var, width=50)
        self.dir_entry.grid(row=0, column=1, padx=5)
        
        self.browse_btn = ttk.Button(self.control_frame, text="浏览", command=self.browse_directory)
        self.browse_btn.grid(row=0, column=2, padx=5)
        
        # 相似度阈值
        self.threshold_label = ttk.Label(self.control_frame, text="相似度阈值:")
        self.threshold_label.grid(row=1, column=0, padx=5, pady=5)
        
        self.threshold_var = tk.IntVar(value=25)
        self.threshold_scale = ttk.Scale(self.control_frame, from_=0, to=100, 
                                       orient=tk.HORIZONTAL, variable=self.threshold_var)
        self.threshold_scale.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=5)
        
        self.threshold_value_label = ttk.Label(self.control_frame, textvariable=self.threshold_var)
        self.threshold_value_label.grid(row=1, column=2)
        
        # 在搜索按钮旁边添加文件选择按钮
        self.search_frame = ttk.Frame(self.control_frame)
        self.search_frame.grid(row=2, column=0, columnspan=3, pady=10)
        
        self.clipboard_btn = ttk.Button(self.search_frame, text="从剪贴板搜索", command=self.start_clipboard_search)
        self.clipboard_btn.pack(side=tk.LEFT, padx=5)
        
        self.file_btn = ttk.Button(self.search_frame, text="从文件搜索", command=self.start_file_search)
        self.file_btn.pack(side=tk.LEFT, padx=5)
        
        # 创建预览区域
        self.preview_frame = ttk.LabelFrame(self.main_frame, text="剪贴板图片预览", padding="5")
        self.preview_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        
        self.preview_label = ttk.Label(self.preview_frame, text="等待图片...")
        self.preview_label.pack(expand=True)
        
        # 创建结果显示区域
        self.result_frame = ttk.LabelFrame(self.main_frame, text="搜索结果", padding="5")
        self.result_frame.grid(row=1, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5, padx=5)
        
        self.scrollable_result = ScrollableFrame(self.result_frame)
        self.scrollable_result.pack(expand=True, fill="both")
        
        # 状态栏
        self.status_var = tk.StringVar(value="就绪")
        self.status_bar = ttk.Label(self.main_frame, textvariable=self.status_var, relief=tk.SUNKEN)
        self.status_bar.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        # 配置网格权重
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.main_frame.columnconfigure(1, weight=1)
        self.main_frame.rowconfigure(1, weight=1)
        
        # 修改相似度变化事件绑定
        self.threshold_var.trace_add("write", self.on_threshold_change_debounced)
        
        # 定时更新预览
        self.update_preview()
    
    def browse_directory(self):
        directory = filedialog.askdirectory(initialdir=self.dir_var.get())
        if directory:
            self.dir_var.set(directory)
    
    def update_preview(self):
        """更新剪贴板图片预览"""
        if not self.preview_enabled:
            return
        
        try:
            clipboard_image = ImageGrab.grabclipboard()
            if clipboard_image:
                preview_size = (200, 200)
                clipboard_image.thumbnail(preview_size, Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(clipboard_image)
                self.preview_label.configure(image=photo)
                self.preview_label.image = photo
            else:
                self.preview_label.configure(image='', text="等待图片...")
        except Exception as e:
            self.preview_label.configure(image='', text="预览失败")
        
        # 每秒更新一次预览
        self.root.after(1000, self.update_preview)
    
    def start_search(self):
        """开始搜索"""
        # 清除旧的显示结果
        for label in self.image_labels:
            label.destroy()
        self.image_labels.clear()
        self.photo_cache.clear()
        self.all_similar_images = []
        
        # 清除预览
        self.preview_label.configure(image='', text="等待图片...")
        
        # 禁用两个搜索按钮
        self.clipboard_btn.configure(state='disabled')
        self.file_btn.configure(state='disabled')
        self.status_var.set("搜索中...")
        
        # 在新线程中执行搜索
        thread = threading.Thread(target=self.search_similar_images)
        thread.daemon = True
        thread.start()
    
    def on_threshold_change_debounced(self, *args):
        """使用防抖动机制处理相似度变化，延迟1秒"""
        if self.threshold_timer:
            self.root.after_cancel(self.threshold_timer)
        self.threshold_timer = self.root.after(1000, self.on_threshold_change)  # 改为1000毫秒（1秒）
    
    def on_threshold_change(self):
        """当相似度阈值改变时只从现有结果中筛选"""
        if self.all_similar_images:
            threshold = self.threshold_var.get()
            filtered_images = [(path, sim) for path, sim in self.all_similar_images 
                             if sim > threshold]
            self.show_image_results(filtered_images)
            # 更新状态栏显示筛选后的数量
            self.update_status(f"找到 {len(filtered_images)} 个相似图片")
    
    def start_clipboard_search(self):
        """从剪贴板开始搜索"""
        self.preview_enabled = True  # 启用剪贴板预览
        clipboard_image = ImageGrab.grabclipboard()
        if clipboard_image:
            self.current_search_image = clipboard_image
            self.start_search()
        else:
            self.update_status("剪贴板中没有图片")

    def start_file_search(self):
        """从文件开始搜索"""
        self.preview_enabled = False  # 禁用剪贴板预览
        file_path = filedialog.askopenfilename(
            filetypes=[
                ("图片文件", "*.jpg *.jpeg *.png *.gif *.bmp *.webp"),
                ("所有文件", "*.*")
            ]
        )
        if file_path:
            try:
                img = Image.open(file_path)
                self.current_search_image = img
                
                # 更新预览
                preview_size = (200, 200)
                img.thumbnail(preview_size, Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self.preview_label.configure(image=photo)
                self.preview_label.image = photo
                
                # 开始搜索
                self.start_search()
            except Exception as e:
                self.update_status(f"打开图片失败: {str(e)}")
                self.preview_enabled = True  # 恢复剪贴板预览

    def get_search_image_hash(self):
        """获取搜索图片的哈希值"""
        try:
            if self.current_search_image is None:
                return None
            
            if self.current_search_image.mode != 'RGB':
                img = self.current_search_image.convert('RGB')
            else:
                img = self.current_search_image
            
            img = img.resize((64, 64), Image.Resampling.LANCZOS)
            
            avg_hash = imagehash.average_hash(img)
            dhash = imagehash.dhash(img)
            phash = imagehash.phash(img)
            
            return (avg_hash, dhash, phash)
        except Exception as e:
            print(f"计算图片哈希值失败: {e}")
            return None

    def search_similar_images(self):
        """搜索相似图片的实现"""
        try:
            # 清除旧的搜索结果和缓存
            self.all_similar_images = []
            self.photo_cache.clear()
            
            directory = self.dir_var.get()
            display_threshold = self.threshold_var.get()
            
            search_hashes = self.get_search_image_hash()
            if search_hashes is None:
                self.update_status("获取搜索图片失败")
                return
            
            similar_images = []
            image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
            processed_count = 0
            total_files = sum(1 for p in Path(directory).rglob('*') 
                             if p.suffix.lower() in image_extensions)
            
            self.update_status("正在搜索...")
            
            def process_image(image_path, search_hashes):
                try:
                    if image_path.suffix.lower() in image_extensions:
                        img_hashes = get_image_hash(image_path)
                        if img_hashes is not None:
                            # 计算三种哈希的平均差异
                            diffs = [h1 - h2 for h1, h2 in zip(search_hashes, img_hashes)]
                            avg_diff = sum(diffs) / len(diffs)
                            similarity = 100 - (avg_diff/64*100)
                            return (image_path, similarity)
                except Exception:
                    pass
                return None
            
            # 使用线程池进行并行处理
            with ThreadPoolExecutor(max_workers=4) as executor:
                process_func = partial(process_image, search_hashes=search_hashes)
                for result in executor.map(process_func, Path(directory).rglob('*')):
                    processed_count += 1
                    if result:
                        similar_images.append(result)
                    if processed_count % 10 == 0:
                        self.update_status(f"正在搜索... {processed_count}/{total_files}")
            
            # 按相似度降序排序
            similar_images.sort(key=lambda x: x[1], reverse=True)
            
            # 存储所有结果
            self.all_similar_images = similar_images
            
            # 显示超过阈值的结果
            filtered_images = [(path, sim) for path, sim in similar_images 
                             if sim > display_threshold]
            
            if filtered_images:
                self.show_image_results(filtered_images)
                self.update_status(f"找到 {len(filtered_images)} 个相似图片")
            else:
                self.update_status("未找到相似图片")
        
        except Exception as e:
            self.update_status(f"搜索出错: {str(e)}")
        
        finally:
            # 恢复按钮状态
            self.root.after(0, lambda: self.clipboard_btn.configure(state='normal'))
            self.root.after(0, lambda: self.file_btn.configure(state='normal'))
    
    def update_status(self, message):
        """更新状态栏"""
        self.root.after(0, lambda: self.status_var.set(message))
    
    async def load_image_async(self, path):
        """异步加载图片"""
        try:
            async with aiofiles.open(path, 'rb') as f:
                data = await f.read()
            img = Image.open(BytesIO(data))
            img.thumbnail((150, 150), Image.Resampling.LANCZOS)
            return img
        except Exception as e:
            print(f"加载图片失败 {path}: {e}")
            return None

    def process_load_queue(self):
        """处理加载队列"""
        if self.load_queue.empty() or not self.is_loading:
            self.is_loading = False
            return

        try:
            frame, path, similarity = self.load_queue.get_nowait()
            
            if path in self.photo_cache:
                self.show_single_result(frame, path, similarity, self.photo_cache[path])
            else:
                # 在线程池中加载图片
                future = self.executor.submit(self.load_image_sync, path)
                self.root.after(100, lambda: self.handle_loaded_image(future, frame, path, similarity))
        except queue.Empty:
            pass

        # 继续处理队列
        self.root.after(50, self.process_load_queue)

    def load_image_sync(self, path):
        """同步加载图片"""
        try:
            img = Image.open(path)
            img.thumbnail((150, 150), Image.Resampling.LANCZOS)
            return img
        except Exception as e:
            print(f"加载图片失败 {path}: {e}")
            return None

    def handle_loaded_image(self, future, frame, path, similarity):
        """处理加载完成的图片"""
        try:
            img = future.result()
            if img:
                photo = ImageTk.PhotoImage(img)
                self.photo_cache[path] = photo
                self.show_single_result(frame, path, similarity, photo)
        except Exception as e:
            print(f"处理图片失败 {path}: {e}")
        finally:
            self.root.after(50, self.process_load_queue)

    def show_single_result(self, frame, path, similarity, photo):
        """显示单个图片结果"""
        img_label = ttk.Label(frame, image=photo)
        img_label.image = photo
        img_label.pack()
        
        text = f"相似度: {similarity:.2f}%"
        text_label = ttk.Label(frame, text=text)
        text_label.pack()
        
        self.image_labels.extend([frame, img_label, text_label])

    def create_context_menu(self):
        """创建右键菜单"""
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="复制原图", command=self.copy_original_image)
        menu.add_command(label="保存原图", command=self.save_original_image)
        return menu

    def show_image_results(self, similar_images):
        """使用简单的分批加载方式显示图片结果"""
        # 清除旧的图片显示
        for label in self.image_labels:
            label.destroy()
        self.image_labels.clear()
        
        columns = 3
        batch_size = 12  # 增加每批加载的数量
        
        def load_batch(start_idx):
            if start_idx >= len(similar_images):
                # 所有图片加载完成后更新状态
                self.update_status(f"找到 {len(self.image_labels) // 3} 个相似图片")
                return
            
            end_idx = min(start_idx + batch_size, len(similar_images))
            current_batch = similar_images[start_idx:end_idx]
            
            for idx, (path, similarity) in enumerate(current_batch, start_idx):
                try:
                    frame = ttk.Frame(self.scrollable_result.scrollable_frame)
                    frame.grid(row=idx // columns, column=idx % columns, padx=5, pady=5)
                    
                    # 使用缓存
                    if path in self.photo_cache:
                        photo = self.photo_cache[path]
                    else:
                        img = Image.open(path)
                        img.thumbnail((150, 150), Image.Resampling.LANCZOS)
                        photo = ImageTk.PhotoImage(img)
                        self.photo_cache[path] = photo
                    
                    img_label = ttk.Label(frame, image=photo)
                    img_label.image = photo
                    img_label.pack()
                    
                    # 存储图片路径
                    img_label.path = path
                    
                    # 绑定点击事件
                    img_label.bind('<Button-1>', lambda e, p=path: self.copy_original_image(p))
                    img_label.bind('<Button-3>', self.show_context_menu)
                    
                    text = f"相似度: {similarity:.2f}%"
                    text_label = ttk.Label(frame, text=text)
                    text_label.pack()
                    
                    self.image_labels.extend([frame, img_label, text_label])
                    
                except Exception as e:
                    print(f"加载图片失败 {path}: {e}")
            
            # 更新加载进度
            self.update_status(f"正在加载... {min(end_idx, len(similar_images))}/{len(similar_images)}")
            
            if end_idx < len(similar_images):
                self.root.after(50, lambda: load_batch(end_idx))
        
        if similar_images:
            self.update_status(f"开始加载 {len(similar_images)} 个图片...")
            load_batch(0)
        else:
            self.update_status("未找到相似图片")

    def show_context_menu(self, event):
        """显示右键菜单"""
        widget = event.widget
        if hasattr(widget, 'path'):
            self.selected_path = widget.path
            menu = self.create_context_menu()
            menu.post(event.x_root, event.y_root)

    def copy_original_image(self, path=None):
        """复制原图到剪贴板"""
        try:
            # 如果是从菜单调用，使用 selected_path
            if path is None and hasattr(self, 'selected_path'):
                path = self.selected_path
            
            if path:
                img = Image.open(path)
                # 转换图片格式
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # 将图片转换为字节流
                output = BytesIO()
                img.convert('RGB').save(output, 'BMP')
                data = output.getvalue()[14:]  # 去除BMP文件头
                output.close()
                
                # 复制到剪贴板
                win32clipboard.OpenClipboard()
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
                win32clipboard.CloseClipboard()
                
                self.update_status(f"已复制图片: {path}")
        except Exception as e:
            self.update_status(f"复制图片失败: {str(e)}")

    def save_original_image(self):
        """保存原图"""
        if hasattr(self, 'selected_path'):
            try:
                file_name = os.path.basename(self.selected_path)
                save_path = filedialog.asksaveasfilename(
                    initialfile=file_name,
                    defaultextension=os.path.splitext(file_name)[1],
                    filetypes=[
                        ("JPEG files", "*.jpg"),
                        ("PNG files", "*.png"),
                        ("All files", "*.*")
                    ]
                )
                if save_path:
                    shutil.copy2(self.selected_path, save_path)
                    self.update_status(f"已保存图片到: {save_path}")
            except Exception as e:
                self.update_status(f"保存图片失败: {str(e)}")

    def show_about(self):
        """显示关于对话框"""
        about_window = tk.Toplevel(self.root)
        about_window.title("关于")
        about_window.geometry("300x400")  # 增加高度以适应图片
        about_window.resizable(False, False)
        
        # 使对话框模态
        about_window.transient(self.root)
        about_window.grab_set()
        
        # 添加图片
        try:
            logo = Image.open("logo.png")  # 确保logo.png在同一目录下
            logo.thumbnail((200, 200))  # 调整图片大小
            photo = ImageTk.PhotoImage(logo)
            logo_label = ttk.Label(about_window, image=photo)
            logo_label.image = photo  # 保持引用
            logo_label.pack(pady=10)
        except Exception:
            pass  # 如果图片加载失败，就跳过
        
        about_text = """图片相似度查找器 v1.0
        
功能特点：
• 支持从剪贴板和文件搜索图片
• 使用图像哈希算法比较相似度
• 可调节相似度阈值
• 支持复制和保存找到的图片

作者：popy
公众号：坡皮黑科技
"""
        
        # 添加文本
        text = tk.Text(about_window, wrap=tk.WORD, padx=10, pady=10)
        text.insert("1.0", about_text)
        text.config(state=tk.DISABLED)  # 使文本只读
        text.pack(expand=True, fill=tk.BOTH)
        
        # 添加确定按钮
        ok_button = ttk.Button(about_window, text="确定", command=about_window.destroy)
        ok_button.pack(pady=10)
        
        # 居中显示窗口
        about_window.update_idletasks()
        width = about_window.winfo_width()
        height = about_window.winfo_height()
        x = (about_window.winfo_screenwidth() // 2) - (width // 2)
        y = (about_window.winfo_screenheight() // 2) - (height // 2)
        about_window.geometry(f"{width}x{height}+{x}+{y}")

def main():
    root = tk.Tk()
    app = ImageFinderGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main() 