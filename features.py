"""Laptop-camera 'sensor': background subtraction -> body blob -> sliding-window motion features."""
import math, collections, numpy as np, cv2
FEATURES = ["ar_end","ar_change","angle_end","height_ratio","max_vy","max_vx","lat_accel","motion_energy"]
class CameraTracker:
    def __init__(self):
        self.bg = cv2.createBackgroundSubtractorMOG2(history=400, varThreshold=40, detectShadows=False)
        self.k = np.ones((5,5), np.uint8)
    def observe(self, frame):
        """Returns (blob or None, energy). blob = dict(cx,cy,w,h,ang,box) in 320x240 coordinates."""
        s = cv2.GaussianBlur(cv2.resize(frame, (320,240)), (5,5), 0)
        m = self.bg.apply(s, learningRate=0.004)
        m = cv2.dilate(cv2.morphologyEx(m, cv2.MORPH_OPEN, self.k), self.k, iterations=2)
        energy = float((m > 0).mean())
        cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cs: return None, energy
        c = max(cs, key=cv2.contourArea)
        if cv2.contourArea(c) < 1200: return None, energy
        x, y, w, h = cv2.boundingRect(c); mo = cv2.moments(c)
        th = 0.5 * math.atan2(2*mo["mu11"], mo["mu20"] - mo["mu02"])
        ang = 90 - abs(math.degrees(th))                  # 0 = upright, 90 = lying flat
        return dict(cx=mo["m10"]/mo["m00"], cy=mo["m01"]/mo["m00"], w=w, h=h, ang=ang, box=(x,y,w,h)), energy
class Window:
    def __init__(self, seconds=1.0): self.sec, self.buf = seconds, collections.deque()
    def add(self, t, blob, energy):
        if blob is not None: self.buf.append((t, blob["cx"], blob["cy"], blob["w"], blob["h"], blob["ang"], energy))
        while self.buf and t - self.buf[0][0] > self.sec: self.buf.popleft()
    def features(self):
        if len(self.buf) < 6: return None
        a = np.array(self.buf); t, cx, cy, w, h, ang, en = a.T
        href = max(h[:3].mean(), 1.0); dt = np.maximum(np.diff(t), 1e-3)
        sm = lambda v: np.convolve(v, np.ones(3)/3, mode="valid")
        vx = np.diff(sm(cx)) / dt[1:-1] / href; vy = np.diff(sm(cy)) / dt[1:-1] / href
        acc = np.abs(np.diff(vx)) / dt[2:-1] if len(vx) > 1 else np.array([0.0])
        ar = w / np.maximum(h, 1)
        return np.array([ar[-3:].mean(), ar[-3:].mean() - ar[:3].mean(), ang[-3:].mean(), h[-3:].mean()/href,
                         max(vy.max(), 0), np.abs(vx).max(), acc.max(), en.mean()])
