import os
import cv2
import numpy as np
import logging
from typing import List, Dict, Any

try:
    from ultralytics import YOLO
    ULTRA_AVAILABLE = True
except ImportError:
    ULTRA_AVAILABLE = False

logger = logging.getLogger(__name__)

class YoloDetector:
    def __init__(self, model_path: str = "yolov8n.pt"):
        self.model_path = model_path
        self.model = None
        self.enabled = ULTRA_AVAILABLE
        if self.enabled:
            try:
                # This will automatically download yolov8n.pt if it doesn't exist
                self.model = YOLO(self.model_path)
                logger.info(f"Loaded YOLO model from {model_path}")
            except Exception as e:
                logger.warning(f"Failed to load YOLO model: {e}")
                self.enabled = False
        else:
            logger.warning("ultralytics not installed. Deep Learning features disabled.")

    def detect(self, img_bgr: np.ndarray, conf_threshold: float = 0.40) -> Dict[str, List[Any]]:
        """
        Runs YOLO inference on the image array.
        Returns a dictionary categorizing bounding boxes.
        """
        results_dict = {
            "doors": [],
            "windows": [],
            "furniture": [],
            "fixtures": []
        }
        if not self.enabled or self.model is None:
            return results_dict

        # Run inference
        results = self.model(img_bgr, conf=conf_threshold, verbose=False)
        if not results:
            return results_dict

        r = results[0]
        boxes = r.boxes

        # COCO class mapping for generic yolov8n.pt
        # If user provides a custom floorplan model, they should update this mapping.
        # COCO IDs: 56:chair, 59:bed, 60:dining table, 61:toilet, 63:sink
        coco_map = {
            56: ('furniture', 'sofa'),
            59: ('furniture', 'bed'),
            60: ('furniture', 'table'),
            61: ('fixtures', 'toilet'),
            63: ('fixtures', 'sink')
        }

        names = self.model.names

        for box in boxes:
            cls_id = int(box.cls[0].item())
            conf = float(box.conf[0].item())
            xyxy = box.xyxy[0].cpu().numpy()
            x1, y1, x2, y2 = map(float, xyxy)
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            w, h = x2 - x1, y2 - y1
            
            name = names.get(cls_id, "").lower()

            # Dynamic routing based on class name
            target_cat = None
            target_type = None

            if 'door' in name:
                target_cat, target_type = 'doors', 'door'
            elif 'window' in name:
                target_cat, target_type = 'windows', 'window'
            elif 'bed' in name:
                target_cat, target_type = 'furniture', 'bed'
            elif 'sofa' in name or 'chair' in name or 'couch' in name:
                target_cat, target_type = 'furniture', 'sofa'
            elif 'table' in name:
                target_cat, target_type = 'furniture', 'table'
            elif 'toilet' in name:
                target_cat, target_type = 'fixtures', 'toilet'
            elif 'sink' in name or 'basin' in name:
                target_cat, target_type = 'fixtures', 'sink'
            elif 'tub' in name or 'bath' in name:
                target_cat, target_type = 'fixtures', 'bathtub'

            # Fallback to COCO map if generic names
            if target_cat is None and cls_id in coco_map:
                target_cat, target_type = coco_map[cls_id]

            if target_cat:
                obj_data = {
                    "cx": cx, "cy": cy,
                    "width": w, "height": h,
                    "angle": 0.0,
                    "confidence": conf
                }
                if target_cat == 'furniture' or target_cat == 'fixtures':
                    obj_data["type"] = target_type
                
                results_dict[target_cat].append(obj_data)

        return results_dict
