import os
import numpy as np
import cv2
from PIL import Image
import fitz
import shutil


class PDFImageComparer:
    def __init__(self, dpi=300):
        self.dpi = dpi
        self.temp_dir = None

    def _ensure_temp_dir(self, base_dir):
        self.temp_dir = os.path.join(base_dir, "temp_images")
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
        os.makedirs(self.temp_dir)
        return self.temp_dir

    def pdf_to_images(self, pdf_path, output_dir=None):
        if output_dir is None:
            output_dir = os.path.join(os.path.dirname(pdf_path), "temp_images")
        
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        print(f"正在将PDF转换为高清图片 (DPI={self.dpi}): {pdf_path}")
        doc = fitz.open(pdf_path)
        zoom = self.dpi / 72
        matrix = fitz.Matrix(zoom, zoom)
        image_paths = []
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            img_path = os.path.join(output_dir, f"page_{page_num + 1}.png")
            img.save(img_path, 'PNG')
            image_paths.append(img_path)
            print(f"  已保存第 {page_num + 1} 页: {img_path}")
        
        doc.close()
        return image_paths

    def resize_image_to_match(self, img1, img2):
        h1, w1 = img1.shape[:2]
        h2, w2 = img2.shape[:2]
        
        if (h1, w1) != (h2, w2):
            print(f"  调整图片尺寸: {w2}x{h2} -> {w1}x{h1}")
            img2 = cv2.resize(img2, (w1, h1))
        
        return img1, img2

    def _cv2_imread(self, img_path):
        """使用numpy来读取图片，避免中文路径问题"""
        img_array = np.fromfile(img_path, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        return img

    def find_differences(self, img1_path, img2_path, threshold=30, min_area=100):
        print(f"正在对比图片差异:")
        print(f"  图片1: {os.path.basename(img1_path)}")
        print(f"  图片2: {os.path.basename(img2_path)}")
        
        img1 = self._cv2_imread(img1_path)
        img2 = self._cv2_imread(img2_path)
        
        if img1 is None or img2 is None:
            print("  警告: 无法读取图片")
            return None, []
        
        img1, img2 = self.resize_image_to_match(img1, img2)
        
        gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)
        
        diff = cv2.absdiff(gray1, gray2)
        
        _, thresh = cv2.threshold(diff, threshold, 255, cv2.THRESH_BINARY)
        
        kernel = np.ones((5, 5), np.uint8)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
        
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        bounding_boxes = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area >= min_area:
                x, y, w, h = cv2.boundingRect(contour)
                padding = 10
                x = max(0, x - padding)
                y = max(0, y - padding)
                w = min(img1.shape[1] - x, w + 2 * padding)
                h = min(img1.shape[0] - y, h + 2 * padding)
                bounding_boxes.append((x, y, w, h))
        
        bounding_boxes = self._merge_overlapping_boxes(bounding_boxes)
        
        print(f"  发现 {len(bounding_boxes)} 处差异")
        return img2, bounding_boxes

    def _merge_overlapping_boxes(self, boxes, distance_threshold=50):
        """合并相邻或重叠的边界框"""
        if not boxes:
            return []
        
        merged = boxes.copy()
        
        while True:
            changed = False
            for i in range(len(merged)):
                for j in range(i + 1, len(merged)):
                    if i >= len(merged) or j >= len(merged):
                        continue
                    
                    x1, y1, w1, h1 = merged[i]
                    x2, y2, w2, h2 = merged[j]
                    
                    # 计算两个框之间的距离
                    dx = max(0, x1 - (x2 + w2), x2 - (x1 + w1))
                    dy = max(0, y1 - (y2 + h2), y2 - (y1 + h1))
                    distance = (dx**2 + dy**2)**0.5
                    
                    if distance <= distance_threshold:
                        # 合并两个框
                        new_x = min(x1, x2)
                        new_y = min(y1, y2)
                        new_w = max(x1 + w1, x2 + w2) - new_x
                        new_h = max(y1 + h1, y2 + h2) - new_y
                        
                        # 替换这两个框
                        merged[i] = (new_x, new_y, new_w, new_h)
                        del merged[j]
                        changed = True
                        break
                if changed:
                    break
            if not changed:
                break
        
        return merged

    def _cv2_imwrite(self, img_path, img):
        """使用numpy来保存图片，避免中文路径问题"""
        ext = os.path.splitext(img_path)[1]
        result, img_encoded = cv2.imencode(ext, img)
        if result:
            img_encoded.tofile(img_path)
        return result

    def draw_bounding_boxes(self, img, boxes, color=(0, 0, 255), thickness=3):
        result_img = img.copy()
        for x, y, w, h in boxes:
            cv2.rectangle(result_img, (x, y), (x + w, y + h), color, thickness)
        return result_img

    def images_to_pdf(self, image_paths, output_pdf_path):
        print(f"正在合成PDF: {output_pdf_path}")
        
        if not image_paths:
            raise ValueError("没有图片可合成PDF")
        
        first_image = Image.open(image_paths[0])
        images = []
        
        for img_path in image_paths[1:]:
            img = Image.open(img_path)
            if img.mode != 'RGB':
                img = img.convert('RGB')
            images.append(img)
        
        if first_image.mode != 'RGB':
            first_image = first_image.convert('RGB')
        
        first_image.save(
            output_pdf_path,
            save_all=True,
            append_images=images
        )
        print(f"PDF已保存: {output_pdf_path}")

    def compare_pdfs(self, pdf_path1, pdf_path2, output_pdf_path=None):
        base_dir = os.path.dirname(pdf_path1)
        temp_dir = self._ensure_temp_dir(base_dir)
        
        pdf1_name = os.path.splitext(os.path.basename(pdf_path1))[0]
        pdf2_name = os.path.splitext(os.path.basename(pdf_path2))[0]
        
        pdf1_dir = os.path.join(temp_dir, pdf1_name)
        pdf2_dir = os.path.join(temp_dir, pdf2_name)
        output_dir = os.path.join(temp_dir, "annotated")
        
        os.makedirs(pdf1_dir)
        os.makedirs(pdf2_dir)
        os.makedirs(output_dir)
        
        print("=" * 60)
        print("步骤1: PDF转图片")
        print("=" * 60)
        images1 = self.pdf_to_images(pdf_path1, pdf1_dir)
        images2 = self.pdf_to_images(pdf_path2, pdf2_dir)
        
        num_pages = max(len(images1), len(images2))
        print(f"\n总页数: {num_pages}")
        
        annotated_image_paths = []
        all_differences = []
        
        print("\n" + "=" * 60)
        print("步骤2: 图片对比与标注")
        print("=" * 60)
        
        for page_num in range(num_pages):
            print(f"\n--- 第 {page_num + 1} 页 ---")
            
            img1_path = images1[page_num] if page_num < len(images1) else None
            img2_path = images2[page_num] if page_num < len(images2) else None
            
            if img1_path is None:
                print("  版本A无此页")
                annotated_image_paths.append(img2_path)
                continue
            
            if img2_path is None:
                print("  版本B无此页")
                annotated_image_paths.append(img1_path)
                continue
            
            annotated_img, boxes = self.find_differences(img1_path, img2_path, threshold=40, min_area=200)
            
            if annotated_img is not None:
                annotated_img = self.draw_bounding_boxes(annotated_img, boxes)
                output_img_path = os.path.join(output_dir, f"annotated_page_{page_num + 1}.png")
                self._cv2_imwrite(output_img_path, annotated_img)
                annotated_image_paths.append(output_img_path)
                
                all_differences.append({
                    "page": page_num + 1,
                    "num_differences": len(boxes),
                    "boxes": boxes
                })
            else:
                annotated_image_paths.append(img2_path)
        
        print("\n" + "=" * 60)
        print("步骤3: 合成标注PDF")
        print("=" * 60)
        
        if output_pdf_path is None:
            output_pdf_path = os.path.join(base_dir, f"{pdf2_name}_标注差异.pdf")
        
        self.images_to_pdf(annotated_image_paths, output_pdf_path)
        
        print("\n" + "=" * 60)
        print("对比完成!")
        print("=" * 60)
        print(f"\n差异汇总:")
        total_differences = sum(d["num_differences"] for d in all_differences)
        print(f"  总差异数: {total_differences}")
        print(f"  有差异的页数: {len(all_differences)}")
        for d in all_differences:
            print(f"    第 {d['page']} 页: {d['num_differences']} 处差异")
        
        print(f"\n输出文件: {output_pdf_path}")
        
        return {
            "output_pdf": output_pdf_path,
            "differences": all_differences,
            "total_differences": total_differences
        }


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    pdf_path1 = os.path.join(script_dir, "合同版本A.pdf")
    pdf_path2 = os.path.join(script_dir, "合同版本B.pdf")
    output_pdf = os.path.join(script_dir, "合同版本B_标注差异.pdf")
    
    comparer = PDFImageComparer(dpi=300)
    
    try:
        result = comparer.compare_pdfs(pdf_path1, pdf_path2, output_pdf)
        print("\n" + "=" * 60)
        print("处理成功完成!")
        print("=" * 60)
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
