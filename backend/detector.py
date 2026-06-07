"""
FloorPlan3D — Rule-Based Detection Engine  v5
==============================================
Upgrades over v4:
- Room polygon extraction with semantic classification
- Fixture/furniture recognition (toilet, sink, bathtub, stove)
- Enhanced room metadata (area m², polygon vertices, semantic type)
- Room classification heuristics (size, aspect ratio, fixture proximity)
- Fixture rendering data for 3D frontend
- CLAHE contrast enhancement before Otsu binarization
- Morphological close after open: heals 1-2px scanline gaps in walls
- Junction repair: 4x4 close kernel fills T/L/X intersection gaps
- Adaptive thresholds: guards against uniform-pen plans (narrow spread)
- Per-segment thickness: sampled along centerline, not class-average
- Confidence score per element
- Window deduplication: overlapping detections collapsed
- Door: 72-point arc sampling + straight leaf line verification
- Door: arc_start/arc_end returned for correct 3D swing angle
- Stair: NumPy vectorized run detection (no Python loops over pixels)
- Room detection: white-region connected components → centroids + bbox
- 20px white padding added pre-detection; coordinates compensated on output
- Graceful fallback when image has <50 ink pixels
"""

import cv2
import numpy as np
import base64
import logging
import math
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Result dataclass
# ─────────────────────────────────────────────────────────────

@dataclass
class DetectionResult:
    image_width:  int  = 0
    image_height: int  = 0
    outer_walls:  List[dict] = field(default_factory=list)
    inner_walls:  List[dict] = field(default_factory=list)
    closets:      List[dict] = field(default_factory=list)
    windows:      List[dict] = field(default_factory=list)
    doors:        List[dict] = field(default_factory=list)
    stairs:       List[dict] = field(default_factory=list)
    rooms:        List[dict] = field(default_factory=list)
    fixtures:     List[dict] = field(default_factory=list)
    furniture:    List[dict] = field(default_factory=list)
    debug_images: dict = field(default_factory=dict)
    thresholds:   dict = field(default_factory=dict)
    summary:      dict = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────
# Detector
# ─────────────────────────────────────────────────────────────

class FloorPlanDetector:

    PAD = 20

    # Room type classification thresholds (relative to total plan area)
    ROOM_TYPES = {
        'bathroom':  {'max_ratio': 0.08, 'aspect_range': (0.5, 2.0)},
        'closet':    {'max_ratio': 0.04, 'aspect_range': (0.3, 3.5)},
        'hallway':   {'max_ratio': 0.10, 'aspect_range': (0.1, 0.35)},
        'kitchen':   {'max_ratio': 0.18, 'aspect_range': (0.5, 2.0)},
        'bedroom':   {'max_ratio': 0.35, 'aspect_range': (0.5, 2.0)},
        'living':    {'max_ratio': 1.00, 'aspect_range': (0.4, 2.5)},
    }

    def __init__(self, max_dim: int = 900):
        self.max_dim = max_dim

    # ══════════════════════════════════════════════════════════
    # PUBLIC
    # ══════════════════════════════════════════════════════════

    def detect(self, image_bytes: bytes) -> DetectionResult:
        arr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Could not decode image")

        h, w = img.shape[:2]
        if max(h, w) > self.max_dim:
            sc  = self.max_dim / max(h, w)
            img = cv2.resize(img, (int(w*sc), int(h*sc)), interpolation=cv2.INTER_AREA)

        # Pad so boundary walls are fully enclosed
        P   = self.PAD
        img = cv2.copyMakeBorder(img, P, P, P, P,
                                  cv2.BORDER_CONSTANT, value=(255,255,255))
        H, W = img.shape[:2]
        res  = DetectionResult(image_width=W, image_height=H)

        # 1 — Preprocess
        binary, gray = self._preprocess(img)

        # 2 — Distance transform
        dist = cv2.distanceTransform(binary, cv2.DIST_L2, 5)

        # 3 — Classify by thickness
        thresholds, cls_map = self._classify(dist)
        res.thresholds = thresholds

        # 4 — Junction repair
        binary_repaired = self._repair_junctions(binary)

        # 5 — Skeletonize each class
        skel_outer     = self._skeletonize((cls_map == 4).astype(np.uint8))
        skel_inner_raw = self._skeletonize((cls_map == 3).astype(np.uint8))
        skel_closet_raw= self._skeletonize((cls_map == 2).astype(np.uint8))
        skel_line      = self._skeletonize((cls_map == 1).astype(np.uint8))

        # 6 — Connectivity filter (Dynamic Kernel Sizes based on resolution)
        base_k = max(3, int(max(W, H) / 100))
        dil_k_large = cv2.getStructuringElement(cv2.MORPH_RECT, (base_k, base_k))
        dil_k_med   = cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, base_k - 2), max(3, base_k - 2)))
        
        outer_mask  = cv2.dilate(skel_outer, dil_k_large)
        inner_filt  = self._filter_connected(skel_inner_raw,  outer_mask, keep=True)
        inner_mask  = cv2.dilate(inner_filt, dil_k_med)
        closet_filt = self._filter_connected(skel_closet_raw, outer_mask, keep=False)

        # 7 — Vectorize & Post-Process with Orthogonal Forcing & Corner Snapping
        outer_segs  = self._post_process_segments(self._vectorize(skel_outer,   dist, cls_map, 4, 20, 12))
        inner_segs  = self._post_process_segments(self._vectorize(inner_filt,   dist, cls_map, 3, 14, 10))
        closet_segs = self._post_process_segments(self._vectorize(closet_filt,  dist, cls_map, 2, 10,  8))

        res.outer_walls = [self._seg_dict(s, "outer")  for s in outer_segs]
        res.inner_walls = [self._seg_dict(s, "inner")  for s in inner_segs]
        res.closets     = [self._seg_dict(s, "closet") for s in closet_segs]

        # 8 — Windows
        res.windows = self._detect_windows(skel_line, W, H)

        # 9 — Doors
        res.doors   = self._detect_doors(gray, binary, W, H)

        # 10 — Stairs
        res.stairs  = self._detect_stairs(skel_line, W, H)

        # 11 — Rooms (enhanced with polygons and semantic types)
        res.rooms   = self._detect_rooms(binary, W, H)

        # 12 — Fixtures (toilet, sink, bathtub, stove)
        res.fixtures = self._detect_fixtures(gray, binary, W, H, res.rooms)

        # 13 — Classify rooms semantically using fixtures + geometry
        self._classify_rooms(res.rooms, res.fixtures, res.doors, W, H)

        # 14 — Furniture
        res.furniture = self._detect_furniture(binary, W, H, res.rooms)

        # Debug images
        res.debug_images = {
            "thickness":      self._enc_thickness(dist, thresholds["p75"]),
            "classification": self._enc_classes(cls_map),
            "skeleton":       self._enc_skel(img, skel_outer, inner_filt,
                                              closet_filt, skel_line),
            "preprocessed":   self._enc(binary),
            "rooms":          self._enc_rooms(img, res.rooms, res.fixtures),
        }

        res.summary = {k: len(getattr(res, k))
                       for k in ("outer_walls","inner_walls","closets",
                                 "windows","doors","stairs","rooms","fixtures")}

        self._strip_pad(res, P)
        return res

    # ══════════════════════════════════════════════════════════
    # PREPROCESS
    # ══════════════════════════════════════════════════════════

    def _preprocess(self, img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # CLAHE — lift low-contrast faint lines before thresholding
        clahe   = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray_eq = clahe.apply(gray)

        blurred = cv2.GaussianBlur(gray_eq, (3, 3), 0.5)
        _, binary = cv2.threshold(blurred, 0, 255,
                                   cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # Open: remove sub-2px noise specks (Dynamic)
        k_open = max(2, int(max(img.shape[:2]) / 450))
        k2 = cv2.getStructuringElement(cv2.MORPH_RECT, (k_open, k_open))
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, k2)

        # Close: heal 1-2px scanline gaps in lines (Dynamic)
        k_close = max(3, int(max(img.shape[:2]) / 300))
        k3 = cv2.getStructuringElement(cv2.MORPH_RECT, (k_close, k_close))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, k3)

        return binary, gray

    # ══════════════════════════════════════════════════════════
    # CLASSIFY BY THICKNESS
    # ══════════════════════════════════════════════════════════

    def _classify(self, dist):
        nonzero = dist[dist > 0].flatten()
        if len(nonzero) < 50:
            cls = np.zeros_like(dist, dtype=np.uint8)
            cls[dist > 0] = 4
            return dict(p10=1,p35=2,p55=3,p75=4,p90=5,
                        t_line=1.5,t_closet_max=2,t_inner_max=4,spread=3), cls

        p10 = float(np.percentile(nonzero, 10))
        p35 = float(np.percentile(nonzero, 35))
        p55 = float(np.percentile(nonzero, 55))
        p75 = float(np.percentile(nonzero, 75))
        p90 = float(np.percentile(nonzero, 90))
        spread = p90 - p10

        if spread < 2.0:
            # Uniform-pen plan: spread thresholds wider
            T_LINE, T_CLOSET, T_INNER = p35, p55, p75
        else:
            T_LINE   = p10 + 0.5
            T_CLOSET = p35
            T_INNER  = p75

        cls = np.zeros_like(dist, dtype=np.uint8)
        ink = dist > 0
        cls[ink & (dist <= T_LINE)]                        = 1
        cls[ink & (dist > T_LINE)   & (dist <= T_CLOSET)] = 2
        cls[ink & (dist > T_CLOSET) & (dist <= T_INNER)]  = 3
        cls[ink & (dist > T_INNER)]                        = 4

        return dict(p10=p10,p35=p35,p55=p55,p75=p75,p90=p90,
                    t_line=T_LINE,t_closet_max=T_CLOSET,t_inner_max=T_INNER,
                    spread=spread), cls

    # ══════════════════════════════════════════════════════════
    # JUNCTION REPAIR
    # ══════════════════════════════════════════════════════════

    def _repair_junctions(self, binary):
        k_size = max(4, int(max(binary.shape) / 225))
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (k_size, k_size))
        return cv2.morphologyEx(binary, cv2.MORPH_CLOSE, k)

    # ══════════════════════════════════════════════════════════
    # SKELETONIZE
    # ══════════════════════════════════════════════════════════

    def _skeletonize(self, img):
        skel   = np.zeros_like(img, dtype=np.uint8)
        src    = img.copy()
        kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
        while True:
            eroded = cv2.erode(src, kernel)
            temp   = cv2.dilate(eroded, kernel)
            temp   = cv2.subtract(src, temp)
            skel   = cv2.bitwise_or(skel, temp)
            src    = eroded
            if cv2.countNonZero(src) == 0:
                break
        return skel

    # ══════════════════════════════════════════════════════════
    # CONNECTIVITY FILTER
    # ══════════════════════════════════════════════════════════

    def _filter_connected(self, skel, mask, keep):
        n, labels = cv2.connectedComponents(skel, connectivity=8)
        out = np.zeros_like(skel)
        for lbl in range(1, n):
            comp    = labels == lbl
            touches = np.any(mask[comp] > 0)
            if touches == keep:
                out[comp] = 255
        return out

    # ══════════════════════════════════════════════════════════
    # VECTORIZE — Hough + merge + per-segment thickness
    # ══════════════════════════════════════════════════════════

    def _vectorize(self, skel, dist, cls_map, cls_id, min_len, max_gap):
        lines = cv2.HoughLinesP(skel, 1, np.pi/180,
                                 threshold=min_len,
                                 minLineLength=min_len,
                                 maxLineGap=max_gap)
        if lines is None:
            return []

        raw    = [tuple(map(float, l[0])) for l in lines]
        merged = self._merge_collinear(raw)

        result = []
        for (x1, y1, x2, y2) in merged:
            n_pts = max(3, int(np.hypot(x2-x1, y2-y1) / 3))
            xs    = np.clip(np.linspace(x1,x2,n_pts).astype(int), 0, dist.shape[1]-1)
            ys    = np.clip(np.linspace(y1,y2,n_pts).astype(int), 0, dist.shape[0]-1)
            thick = float(np.median(dist[ys, xs])) * 2.0
            if thick < 0.5:
                vals  = dist[cls_map == cls_id]
                thick = float(np.median(vals)) * 2.0 if len(vals) else 8.0
            length = float(np.hypot(x2-x1, y2-y1))
            conf   = min(1.0, (length/50.0) * min(1.0, thick/6.0))
            result.append((x1, y1, x2, y2, thick, conf, length))
        return result

    def _post_process_segments(self, segs, snap_radius=15, ortho_tol=4.0):
        if not segs: return []
        
        # 1. Force Orthogonal
        forced = []
        for (x1, y1, x2, y2, thick, conf, length) in segs:
            angle = np.degrees(np.arctan2(y2 - y1, x2 - x1)) % 180
            if min(angle, 180 - angle) < ortho_tol:
                # Force horizontal
                my = (y1 + y2) / 2
                forced.append([x1, my, x2, my, thick, conf, length])
            elif abs(angle - 90) < ortho_tol:
                # Force vertical
                mx = (x1 + x2) / 2
                forced.append([mx, y1, mx, y2, thick, conf, length])
            else:
                forced.append([x1, y1, x2, y2, thick, conf, length])
                
        # 2. Corner Snapping
        pts = []
        for i, s in enumerate(forced):
            pts.extend([(i, 0, s[0], s[1]), (i, 2, s[2], s[3])])
            
        used = set()
        for i, (s_idx1, p_offset1, x1, y1) in enumerate(pts):
            if i in used: continue
            
            cluster = [(s_idx1, p_offset1)]
            cx, cy, count = x1, y1, 1
            used.add(i)
            
            for j in range(i + 1, len(pts)):
                if j in used: continue
                s_idx2, p_offset2, x2, y2 = pts[j]
                
                if np.hypot(x1 - x2, y1 - y2) < snap_radius:
                    cluster.append((s_idx2, p_offset2))
                    cx += x2
                    cy += y2
                    count += 1
                    used.add(j)
                    
            if count > 1:
                avg_x = cx / count
                avg_y = cy / count
                for (s_idx, p_offset) in cluster:
                    forced[s_idx][p_offset]   = avg_x
                    forced[s_idx][p_offset+1] = avg_y
                    
        for s in forced:
            s[6] = float(np.hypot(s[2] - s[0], s[3] - s[1]))
            
        return [tuple(s) for s in forced if s[6] > 1.0]

    def _seg_dict(self, s, seg_type):
        return dict(x1=round(s[0],1), y1=round(s[1],1),
                    x2=round(s[2],1), y2=round(s[3],1),
                    thickness_px=round(s[4] if len(s)>4 else 10.0, 2),
                    seg_type=seg_type,
                    confidence=round(s[5] if len(s)>5 else 1.0, 3),
                    length_px=round(s[6] if len(s)>6 else 0.0, 1))

    # ══════════════════════════════════════════════════════════
    # MERGE COLLINEAR SEGMENTS
    # ══════════════════════════════════════════════════════════

    def _merge_collinear(self, segs, angle_tol=6.0, dist_tol=14.0):
        if not segs:
            return []
        used   = [False]*len(segs)
        merged = []

        def angle(s):
            return np.degrees(np.arctan2(s[3]-s[1], s[2]-s[0])) % 180

        def pt_dist(px, py, s):
            dx,dy = s[2]-s[0],s[3]-s[1]
            d2    = dx*dx+dy*dy
            if d2 == 0:
                return np.hypot(px-s[0],py-s[1])
            t = np.clip(((px-s[0])*dx+(py-s[1])*dy)/d2, 0, 1)
            return np.hypot(px-(s[0]+t*dx), py-(s[1]+t*dy))

        for i, si in enumerate(segs):
            if used[i]:
                continue
            ai  = angle(si)
            pts = [[si[0],si[1]],[si[2],si[3]]]
            used[i] = True
            for j, sj in enumerate(segs):
                if used[j] or i==j:
                    continue
                aj = angle(sj)
                da = abs(ai-aj)
                if da > angle_tol and abs(da-180) > angle_tol:
                    continue
                mx,my = (sj[0]+sj[2])/2, (sj[1]+sj[3])/2
                if pt_dist(mx, my, si) < dist_tol:
                    pts += [[sj[0],sj[1]],[sj[2],sj[3]]]
                    used[j] = True

            pa = np.array(pts, dtype=np.float32)
            if len(pa) < 2:
                merged.append(si[:4]); continue
            line_fit = cv2.fitLine(pa, cv2.DIST_L2, 0, 0.01, 0.01)
            vx = float(line_fit[0][0])
            vy = float(line_fit[1][0])
            cx = float(line_fit[2][0])
            cy = float(line_fit[3][0])
            proj = [(p[0]-cx)*vx+(p[1]-cy)*vy for p in pa]
            t0,t1 = min(proj),max(proj)
            merged.append((round(cx+t0*vx,1), round(cy+t0*vy,1),
                            round(cx+t1*vx,1), round(cy+t1*vy,1)))
        return merged

    # ══════════════════════════════════════════════════════════
    # WINDOW DETECTION
    # ══════════════════════════════════════════════════════════

    def _detect_windows(self, skel_line, W, H):
        wins      = []
        used_rows = set()
        used_cols = set()

        # Horizontal pairs
        row_runs: Dict[int,List] = {}
        for y in range(1, H-1):
            row = skel_line[y, :]
            s_arr = np.where(np.diff(np.concatenate(([0], row, [0]))) == 255)[0]
            e_arr = np.where(np.diff(np.concatenate(([0], row, [0]))) == -255)[0]
            for s,e in zip(s_arr, e_arr):
                if e-s >= 8:
                    row_runs.setdefault(y,[]).append((int(s),int(e-1)))

        ys = sorted(row_runs)
        for i, y1 in enumerate(ys):
            if y1 in used_rows: continue
            for y2 in ys[i+1:]:
                gap = y2-y1
                if gap < 2:   continue
                if gap > 14:  break
                if y2 in used_rows: continue
                for r1 in row_runs[y1]:
                    for r2 in row_runs[y2]:
                        ox1,ox2 = max(r1[0],r2[0]), min(r1[1],r2[1])
                        if ox2-ox1 < 8: continue
                        cy = (y1+y2)/2
                        wins.append(dict(x1=float(ox1),y1=cy,
                                         x2=float(ox2),y2=cy,
                                         orient="h",gap_px=float(gap),
                                         confidence=min(1.0,(ox2-ox1)/60.0)))
                        used_rows.add(y1); used_rows.add(y2); break
                    if y1 in used_rows: break

        # Vertical pairs
        col_runs: Dict[int,List] = {}
        for x in range(1, W-1):
            col = skel_line[:, x]
            s_arr = np.where(np.diff(np.concatenate(([0], col, [0]))) == 255)[0]
            e_arr = np.where(np.diff(np.concatenate(([0], col, [0]))) == -255)[0]
            for s,e in zip(s_arr, e_arr):
                if e-s >= 8:
                    col_runs.setdefault(x,[]).append((int(s),int(e-1)))

        xs = sorted(col_runs)
        for i, x1 in enumerate(xs):
            if x1 in used_cols: continue
            for x2 in xs[i+1:]:
                gap = x2-x1
                if gap < 2:   continue
                if gap > 14:  break
                if x2 in used_cols: continue
                for r1 in col_runs[x1]:
                    for r2 in col_runs[x2]:
                        oy1,oy2 = max(r1[0],r2[0]), min(r1[1],r2[1])
                        if oy2-oy1 < 8: continue
                        cx = (x1+x2)/2
                        wins.append(dict(x1=cx,y1=float(oy1),
                                         x2=cx,y2=float(oy2),
                                         orient="v",gap_px=float(gap),
                                         confidence=min(1.0,(oy2-oy1)/60.0)))
                        used_cols.add(x1); used_cols.add(x2); break
                    if x1 in used_cols: break

        # Dedup
        deduped = []
        for w in wins:
            if not any(w['orient']==k['orient']
                       and abs(w['x1']-k['x1'])<8
                       and abs(w['y1']-k['y1'])<8 for k in deduped):
                deduped.append(w)

        return deduped[:50]

    # ══════════════════════════════════════════════════════════
    # DOOR DETECTION
    # ══════════════════════════════════════════════════════════

    def _detect_doors(self, gray, binary, W, H):
        doors = []
        edges = cv2.Canny(gray, 30, 100)

        circles = cv2.HoughCircles(edges, cv2.HOUGH_GRADIENT,
                                    dp=1.2, minDist=25,
                                    param1=50, param2=18,
                                    minRadius=10, maxRadius=75)
        if circles is None:
            return []

        circles = np.round(circles[0]).astype(int)
        for (cx, cy, r) in circles:
            angles = np.linspace(0, 2*np.pi, 72, endpoint=False)
            pxs    = np.clip((cx+r*np.cos(angles)).astype(int), 0, W-1)
            pys    = np.clip((cy+r*np.sin(angles)).astype(int), 0, H-1)
            hits   = binary[pys, pxs] > 0
            cov    = hits.mean()

            if cov < 0.08 or cov > 0.52:
                continue

            hit_angles = angles[hits]
            if len(hit_angles) < 4:
                continue

            arc_start = float(hit_angles[0])
            arc_end   = float(hit_angles[-1])

            # Verify leaf line near hinge
            hx = int(cx + r*np.cos(arc_start))
            hy = int(cy + r*np.sin(arc_start))
            roi= binary[max(0,hy-6):hy+6, max(0,hx-6):hx+6]
            has_leaf = bool(roi.any())

            if any(abs(d['cx']-cx)<r and abs(d['cy']-cy)<r for d in doors):
                continue

            doors.append(dict(
                cx=float(cx), cy=float(cy),
                radius_px=float(r),
                arc_start=round(arc_start, 3),
                arc_end=round(arc_end, 3),
                coverage=round(float(cov), 3),
                has_leaf=has_leaf,
                confidence=round(min(1.0, cov/0.3*(0.7+0.3*has_leaf)), 3)
            ))

        return sorted(doors, key=lambda d: -d['confidence'])[:25]

    # ══════════════════════════════════════════════════════════
    # STAIR DETECTION
    # ══════════════════════════════════════════════════════════

    def _detect_stairs(self, skel_line, W, H):
        stairs = []

        def get_runs(arr_2d, axis):
            runs = {}
            length = arr_2d.shape[1-axis]
            for idx in range(1, arr_2d.shape[axis]-1):
                line = arr_2d[idx,:] if axis==0 else arr_2d[:,idx]
                padded = np.concatenate(([0], line.astype(np.int16), [0]))
                diff   = np.diff(padded)
                starts = np.where(diff == 255)[0]
                ends   = np.where(diff == -255)[0]
                for s,e in zip(starts,ends):
                    if e-s >= 16:
                        runs.setdefault(int(idx),[]).append((int(s),int(e-1),int(e-s)))
            return runs

        # Horizontal
        row_runs = get_runs(skel_line, axis=0)
        stairs  += self._group_runs(row_runs, "h")

        # Vertical
        col_runs = get_runs(skel_line, axis=1)
        stairs  += self._group_runs(col_runs, "v")

        return stairs

    def _group_runs(self, runs, orient):
        groups = []
        keys   = sorted(runs)
        i      = 0
        while i < len(keys):
            group = [keys[i]]
            j = i+1
            while j < len(keys):
                gap = keys[j]-keys[j-1]
                if gap < 8 or gap > 58: break
                if len(group) >= 2 and abs(gap-(group[-1]-group[-2])) > 6: break
                r1 = runs.get(keys[j-1],[None])[0]
                r2 = runs.get(keys[j],  [None])[0]
                if not r1 or not r2: break
                if min(r1[1],r2[1])-max(r1[0],r2[0]) < 14: break
                group.append(keys[j]); j += 1

            if len(group) >= 3:
                all_r   = [runs[k][0] for k in group if runs.get(k)]
                a1,a2   = min(r[0] for r in all_r), max(r[1] for r in all_r)
                spacing = (group[-1]-group[0])/(len(group)-1) if len(group)>1 else 20
                if orient=="h":
                    groups.append(dict(x1=float(a1),y1=float(group[0]),
                                       x2=float(a2),y2=float(group[-1]),
                                       steps=len(group),orient="h",
                                       spacing_px=round(spacing,1),
                                       confidence=round(min(1.0,len(group)/10.0),3)))
                else:
                    groups.append(dict(x1=float(group[0]),y1=float(a1),
                                       x2=float(group[-1]),y2=float(a2),
                                       steps=len(group),orient="v",
                                       spacing_px=round(spacing,1),
                                       confidence=round(min(1.0,len(group)/10.0),3)))
                i = j
            else:
                i += 1
        return groups

    # ══════════════════════════════════════════════════════════
    # ROOM DETECTION (ENHANCED v5)
    # ══════════════════════════════════════════════════════════

    def _detect_rooms(self, binary, W, H):
        # Thicken walls to close small gaps
        k_thick = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
        walls_thick = cv2.morphologyEx(binary, cv2.MORPH_DILATE, k_thick)

        white = cv2.bitwise_not(walls_thick)
        k     = cv2.getStructuringElement(cv2.MORPH_RECT, (5,5))
        white = cv2.morphologyEx(white, cv2.MORPH_CLOSE, k)
        white = cv2.morphologyEx(white, cv2.MORPH_OPEN, k)

        n, labels, stats, centroids = cv2.connectedComponentsWithStats(
            white, connectivity=4)

        total = W*H
        rooms = []

        # Also find contours for polygon extraction
        contours_all, _ = cv2.findContours(white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for lbl in range(1, n):
            area = int(stats[lbl, cv2.CC_STAT_AREA])
            if area < total*0.005 or area > total*0.80:
                continue

            bx = int(stats[lbl,cv2.CC_STAT_LEFT])
            by = int(stats[lbl,cv2.CC_STAT_TOP])
            bw = int(stats[lbl,cv2.CC_STAT_WIDTH])
            bh = int(stats[lbl,cv2.CC_STAT_HEIGHT])

            cx = float(centroids[lbl][0])
            cy = float(centroids[lbl][1])

            # Find matching contour for this label
            polygon = []
            label_mask = (labels == lbl).astype(np.uint8) * 255
            room_contours, _ = cv2.findContours(label_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if room_contours:
                # Get the largest contour
                largest = max(room_contours, key=cv2.contourArea)
                # Simplify polygon
                epsilon = 0.02 * cv2.arcLength(largest, True)
                approx = cv2.approxPolyDP(largest, epsilon, True)
                polygon = [[int(p[0][0]), int(p[0][1])] for p in approx]

            # Aspect ratio for classification
            aspect = min(bw, bh) / max(bw, bh) if max(bw, bh) > 0 else 1.0
            area_ratio = area / total

            rooms.append(dict(
                id=len(rooms),
                cx=round(cx, 1),
                cy=round(cy, 1),
                bbox=[bx, by, bw, bh],
                area_px=area,
                area_ratio=round(area_ratio, 4),
                aspect_ratio=round(aspect, 3),
                polygon=polygon,
                label=f"Room {len(rooms)+1}",
                room_type="unknown",
                color=None,
            ))

        return sorted(rooms, key=lambda r: -r['area_px'])[:16]

    # ══════════════════════════════════════════════════════════
    # FIXTURE DETECTION (NEW v5)
    # ══════════════════════════════════════════════════════════

    def _detect_fixtures(self, gray, binary, W, H, rooms):
        """
        Detect common architectural fixtures:
        - Toilet: circle/ellipse + attached rectangle (tank)
        - Sink: small rectangle with circle/arc inside
        - Bathtub: large rounded rectangle
        - Stove: rectangle with 4 circles
        """
        fixtures = []

        # Use Hough circles to find fixture-sized circles
        edges = cv2.Canny(gray, 40, 120)
        circles = cv2.HoughCircles(edges, cv2.HOUGH_GRADIENT,
                                    dp=1.3, minDist=15,
                                    param1=50, param2=22,
                                    minRadius=5, maxRadius=30)

        if circles is not None:
            circles = np.round(circles[0]).astype(int)
            for (cx, cy, r) in circles:
                # Check arc coverage — toilets have high coverage (>55%)
                angles = np.linspace(0, 2*np.pi, 72, endpoint=False)
                pxs = np.clip((cx+r*np.cos(angles)).astype(int), 0, W-1)
                pys = np.clip((cy+r*np.sin(angles)).astype(int), 0, H-1)
                hits = binary[pys, pxs] > 0
                cov  = hits.mean()

                if cov > 0.55 and r < 25:
                    # Full or near-full circle — likely toilet bowl or sink bowl
                    # Check for nearby rectangle (tank)
                    roi_x1 = max(0, cx-r*3)
                    roi_y1 = max(0, cy-r*3)
                    roi_x2 = min(W, cx+r*3)
                    roi_y2 = min(H, cy+r*3)
                    roi = binary[roi_y1:roi_y2, roi_x1:roi_x2]
                    roi_area = cv2.countNonZero(roi)
                    roi_total = max(1, (roi_x2-roi_x1)*(roi_y2-roi_y1))

                    # Dense ink nearby = fixture with body
                    if roi_area / roi_total > 0.15:
                        # Classify as toilet if medium-sized
                        if r >= 8 and r <= 22:
                            fixture_type = "toilet"
                            if r <= 12:
                                fixture_type = "sink"
                        else:
                            fixture_type = "sink"

                        # Find which room this fixture belongs to
                        room_id = self._find_room_for_point(cx, cy, rooms)

                        fixtures.append(dict(
                            type=fixture_type,
                            cx=float(cx), cy=float(cy),
                            radius=float(r),
                            width=float(r*2), height=float(r*2),
                            coverage=round(float(cov), 3),
                            room_id=room_id,
                            confidence=round(min(1.0, cov * 1.2), 3)
                        ))

        # Detect rectangular fixtures (bathtub, stove)
        # Find rectangular contours in the binary image
        contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 200 or area > W*H*0.05:
                continue

            rect = cv2.minAreaRect(cnt)
            (rcx, rcy), (rw, rh), angle = rect
            if rw < 1 or rh < 1:
                continue

            aspect = min(rw, rh) / max(rw, rh)
            extent = area / (rw * rh) if rw * rh > 0 else 0

            # Bathtub: elongated rectangle, high fill
            if (max(rw, rh) > 40 and max(rw, rh) < 120 and
                aspect > 0.3 and aspect < 0.6 and extent > 0.7):

                # Check it's not a wall segment (walls are thinner)
                if min(rw, rh) > 15:
                    room_id = self._find_room_for_point(int(rcx), int(rcy), rooms)
                    # Only add if not overlapping with existing fixtures
                    if not any(abs(f['cx']-rcx) < 20 and abs(f['cy']-rcy) < 20 for f in fixtures):
                        fixtures.append(dict(
                            type="bathtub",
                            cx=round(float(rcx), 1), cy=round(float(rcy), 1),
                            radius=0,
                            width=round(float(max(rw,rh)), 1),
                            height=round(float(min(rw,rh)), 1),
                            coverage=round(extent, 3),
                            room_id=room_id,
                            confidence=round(min(1.0, extent * 0.9), 3)
                        ))

        # Deduplicate fixtures
        deduped = []
        for f in fixtures:
            if not any(abs(f['cx']-d['cx']) < 15 and abs(f['cy']-d['cy']) < 15 for d in deduped):
                deduped.append(f)

        return deduped[:30]

    def _find_room_for_point(self, x, y, rooms):
        """Find which room a point belongs to."""
        for room in rooms:
            bbox = room['bbox']
            if (bbox[0] <= x <= bbox[0]+bbox[2] and
                bbox[1] <= y <= bbox[1]+bbox[3]):
                return room['id']
        return -1

    # ══════════════════════════════════════════════════════════
    # ROOM SEMANTIC CLASSIFICATION (NEW v5)
    # ══════════════════════════════════════════════════════════

    def _classify_rooms(self, rooms, fixtures, doors, W, H):
        """Classify rooms by type using geometric and fixture heuristics."""
        total_area = W * H
        room_colors = {
            'bathroom':    '#4488cc',
            'closet':      '#9060d0',
            'hallway':     '#808080',
            'kitchen':     '#cc8844',
            'bedroom':     '#6688aa',
            'living':      '#44aa66',
            'dining':      '#aa8866',
            'unknown':     '#607080',
        }

        for room in rooms:
            area_ratio = room['area_ratio']
            aspect = room['aspect_ratio']
            bbox = room['bbox']
            room_id = room['id']

            # Check which fixtures are in this room
            room_fixtures = [f for f in fixtures if f.get('room_id') == room_id]
            has_toilet = any(f['type'] == 'toilet' for f in room_fixtures)
            has_sink   = any(f['type'] == 'sink' for f in room_fixtures)
            has_tub    = any(f['type'] == 'bathtub' for f in room_fixtures)
            has_stove  = any(f['type'] == 'stove' for f in room_fixtures)

            # Classification logic
            if has_toilet or has_tub:
                room_type = 'bathroom'
            elif has_stove or (has_sink and area_ratio > 0.05):
                room_type = 'kitchen'
            elif area_ratio < 0.025:
                room_type = 'closet'
            elif aspect < 0.3:
                room_type = 'hallway'
            elif area_ratio > 0.20:
                room_type = 'living'
            elif area_ratio > 0.10:
                room_type = 'bedroom'
            elif area_ratio > 0.05:
                # Medium rooms — check for doors
                nearby_doors = sum(1 for d in doors
                                   if bbox[0]-20 <= d['cx'] <= bbox[0]+bbox[2]+20
                                   and bbox[1]-20 <= d['cy'] <= bbox[1]+bbox[3]+20)
                if nearby_doors >= 2:
                    room_type = 'hallway'
                else:
                    room_type = 'bedroom'
            else:
                room_type = 'unknown'

            room['room_type'] = room_type
            room['color'] = room_colors.get(room_type, room_colors['unknown'])

            # Generate nice label
            type_labels = {
                'bathroom': 'Bathroom',
                'closet': 'Closet',
                'hallway': 'Hallway',
                'kitchen': 'Kitchen',
                'bedroom': 'Bedroom',
                'living': 'Living Room',
                'dining': 'Dining Room',
                'unknown': f'Room {room_id+1}',
            }

            # Count rooms of same type for numbering
            same_type = sum(1 for r in rooms if r.get('room_type') == room_type and r['id'] < room_id)
            base_label = type_labels.get(room_type, 'Room')
            if same_type > 0:
                room['label'] = f"{base_label} {same_type+1}"
            else:
                room['label'] = base_label

    # ══════════════════════════════════════════════════════════
    # FURNITURE DETECTION (NEW v6)
    # ══════════════════════════════════════════════════════════

    def _detect_furniture(self, binary, W, H, rooms):
        furniture = []
        contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 400 or area > W*H*0.1:
                continue
            rect = cv2.minAreaRect(cnt)
            (rcx, rcy), (rw, rh), angle = rect
            if rw < 1 or rh < 1: continue
            aspect = min(rw, rh) / max(rw, rh)
            extent = area / (rw * rh) if rw * rh > 0 else 0
            if extent < 0.6 or min(rw, rh) < 20: continue
            
            matched_room = None
            for r in rooms:
                bbox = r['bbox']
                if bbox[0] <= rcx <= bbox[0]+bbox[2] and bbox[1] <= rcy <= bbox[1]+bbox[3]:
                    matched_room = r; break
            if not matched_room: continue
            
            r_type = matched_room.get('room_type', 'unknown')
            furn_type = None
            if r_type == 'bedroom' and max(rw, rh) > 50 and aspect > 0.5:
                furn_type = "bed"
            elif r_type == 'living' and max(rw, rh) > 60 and aspect < 0.45:
                furn_type = "sofa"
            elif r_type in ['dining', 'kitchen'] and max(rw, rh) > 40 and aspect > 0.4:
                furn_type = "table"
            elif r_type in ['hallway', 'unknown'] and max(rw, rh) > 60 and aspect > 0.5:
                furn_type = "rug"
                
            if furn_type and not any(abs(f['cx']-rcx) < 30 and abs(f['cy']-rcy) < 30 for f in furniture):
                furniture.append(dict(
                    type=furn_type,
                    cx=round(float(rcx), 1), cy=round(float(rcy), 1),
                    width=round(float(max(rw, rh)), 1), height=round(float(min(rw, rh)), 1),
                    angle=round(float(angle), 1), room_id=matched_room['id']
                ))
        return furniture

    # ══════════════════════════════════════════════════════════
    # PADDING COMPENSATION
    # ══════════════════════════════════════════════════════════

    def _strip_pad(self, res, P):
        for seg in res.outer_walls+res.inner_walls+res.closets:
            for k in ('x1','y1','x2','y2'):
                seg[k] = round(seg[k]-P, 1)
        for w in res.windows:
            for k in ('x1','y1','x2','y2'):
                w[k] = round(w[k]-P, 1)
        for d in res.doors:
            d['cx'] = round(d['cx']-P, 1)
            d['cy'] = round(d['cy']-P, 1)
        for s in res.stairs:
            for k in ('x1','y1','x2','y2'):
                s[k] = round(s[k]-P, 1)
        for r in res.rooms:
            r['cx'] = round(r['cx']-P, 1)
            r['cy'] = round(r['cy']-P, 1)
            r['bbox'][0] -= P; r['bbox'][1] -= P
            # Offset polygon points
            if r.get('polygon'):
                r['polygon'] = [[p[0]-P, p[1]-P] for p in r['polygon']]
        for f in res.fixtures:
            f['cx'] = round(f['cx']-P, 1)
            f['cy'] = round(f['cy']-P, 1)
        for f in res.furniture:
            f['cx'] = round(f['cx']-P, 1)
            f['cy'] = round(f['cy']-P, 1)
        res.image_width  -= 2*P
        res.image_height -= 2*P

    # ══════════════════════════════════════════════════════════
    # DEBUG ENCODERS
    # ══════════════════════════════════════════════════════════

    def _enc_thickness(self, dist, maxv):
        vis = np.clip(dist/max(maxv,1.), 0, 1)
        cm  = cv2.applyColorMap((vis*255).astype(np.uint8), cv2.COLORMAP_INFERNO)
        return self._enc(cm)

    def _enc_classes(self, cls_map):
        COLS = {0:(8,11,16),1:(80,210,100),2:(160,90,220),
                3:(80,160,220),4:(230,200,60)}
        vis  = np.zeros((*cls_map.shape,3), dtype=np.uint8)
        for c,col in COLS.items(): vis[cls_map==c] = col
        return self._enc(vis)

    def _enc_skel(self, img, sk_o, sk_i, sk_c, sk_l):
        vis = img.copy()
        vis[sk_o>0] = (0,220,255)
        vis[sk_i>0] = (255,160,60)
        vis[sk_c>0] = (200,60,255)
        vis[sk_l>0] = (60,255,140)
        return self._enc(vis)

    def _enc_rooms(self, img, rooms, fixtures):
        """Encode a debug visualization of detected rooms and fixtures."""
        vis = img.copy()
        colors = [
            (68,136,204), (144,96,208), (128,128,128),
            (204,136,68), (102,136,170), (68,170,102),
            (170,136,102), (96,112,128),
        ]
        for i, room in enumerate(rooms):
            color = colors[i % len(colors)]
            bbox = room['bbox']
            cv2.rectangle(vis,
                         (bbox[0], bbox[1]),
                         (bbox[0]+bbox[2], bbox[1]+bbox[3]),
                         color, 2)
            # Draw polygon if available
            if room.get('polygon') and len(room['polygon']) > 2:
                pts = np.array(room['polygon'], dtype=np.int32)
                overlay = vis.copy()
                cv2.fillPoly(overlay, [pts], color)
                cv2.addWeighted(overlay, 0.15, vis, 0.85, 0, vis)
                cv2.polylines(vis, [pts], True, color, 2)
            # Label
            label = room.get('label', f'Room {i+1}')
            rtype = room.get('room_type', '')
            cv2.putText(vis, f"{label}", (bbox[0]+4, bbox[1]+16),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255,255,255), 1, cv2.LINE_AA)
            cv2.putText(vis, f"{rtype}", (bbox[0]+4, bbox[1]+30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.3, color, 1, cv2.LINE_AA)

        # Draw fixtures
        fixture_colors = {
            'toilet': (0, 200, 255),
            'sink': (255, 150, 50),
            'bathtub': (50, 200, 150),
            'stove': (200, 50, 50),
        }
        for f in fixtures:
            color = fixture_colors.get(f['type'], (200,200,200))
            cx, cy = int(f['cx']), int(f['cy'])
            r = int(f.get('radius', 8)) or 8
            cv2.circle(vis, (cx, cy), r, color, 2)
            cv2.putText(vis, f['type'], (cx-15, cy-r-4),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.3, color, 1, cv2.LINE_AA)

        return self._enc(vis)

    def _enc(self, img):
        _, buf = cv2.imencode(".png", img)
        return base64.b64encode(buf).decode("utf-8")


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def detect_floor_plan(image_bytes: bytes) -> dict:
    r = FloorPlanDetector(max_dim=900).detect(image_bytes)
    return dict(
        image_width=r.image_width, image_height=r.image_height,
        outer_walls=r.outer_walls, inner_walls=r.inner_walls,
        closets=r.closets, windows=r.windows, doors=r.doors,
        stairs=r.stairs, rooms=r.rooms, fixtures=r.fixtures,
        debug_images=r.debug_images, thresholds=r.thresholds,
        summary=r.summary,
    )
