import time
import numpy as np
import cv2
from flask import Flask, Response, request, jsonify
import multiprocessing
import signal
import os
import mss
import requests

app = Flask(__name__)
select_monitor = 1  # 默认选择第一个显示器


@app.route('/set_monitor/<int:monitor_index>', methods=['GET'])
def set_monitor(monitor_index):
    global select_monitor
    try:
        with mss.mss() as sct:
            if 1 <= monitor_index < len(sct.monitors):
                select_monitor = monitor_index
                return jsonify({'success': True, 'message': f'Monitor set to {monitor_index}'})
            else:
                return jsonify({'success': False, 'message': 'Invalid monitor index'}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/screenshot.jpg')
def get_screenshot():
    with mss.mss() as sct:
        monitor = sct.monitors[select_monitor]
        screenshot = np.array(sct.grab(monitor))

        if screenshot.shape[1] > 1920:
            screenshot = cv2.resize(screenshot, (1920, 1080))

        _, buffer = cv2.imencode('.jpg', screenshot, [
            cv2.IMWRITE_JPEG_QUALITY, 80,
            cv2.IMWRITE_JPEG_OPTIMIZE, 1
        ])

        return Response(buffer.tobytes(), mimetype='image/jpeg')


@app.route('/screen')
def get_screen():
    return Response(generate_screenshots(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')


def generate_screenshots():
    with mss.mss() as sct:
        monitor = sct.monitors[select_monitor]
        current_monitor = select_monitor
        while True:
            if current_monitor != select_monitor:
                monitor = sct.monitors[select_monitor]
            screenshot = np.array(sct.grab(monitor))
            _, buffer = cv2.imencode('.jpg', screenshot,
                                     [cv2.IMWRITE_JPEG_QUALITY, 70])
            frame = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            time.sleep(0.05)


def generate_frames():
    camera = cv2.VideoCapture(2)
    while True:
        success, frame = camera.read()
        if not success:
            with open(r"img/failed.jpeg", "rb") as f:
                frame = f.read()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        else:
            ret, buffer = cv2.imencode('.jpg', frame)
            frame = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')


def run_flask_app(host, port):
    app.run(host=host, port=port, debug=False)


class FlaskApp:
    def __init__(self, core, host='0.0.0.0', port=5000):
        self.host = host
        self.port = port
        self.process = None
        self.core = core
        self.config = [
            {
                "name": "FlaskApp_显示器选择",
                "entity_type": "number",
                "entity_id": "index",
                "icon": "mdi:monitor"
            }]

    def start(self):
        if self.process is None:
            try:
                self.process = multiprocessing.Process(
                    target=run_flask_app, args=(self.host, self.port))
                self.process.start()
                self.core.log.info(f"Flask进程启动 http://{self.host}:{self.port}")
            except Exception as e:
                self.core.log.error(f"Flask进程启动失败: {e}")
        self.core.mqtt.update_state_data(1, "FlaskApp_index", "number")

    def stop(self):
        if self.process is not None:
            os.kill(self.process.pid, signal.SIGTERM)
            self.process.join()
            self.process = None
            self.core.log.debug("Flask进程停止")

    def change_monitor(self, index):
        url = f"http://localhost:5000/set_monitor/{index}"
        try:
            response = requests.get(url)
            data = response.json()
            if data['success']:
                global  select_monitor
                select_monitor = index
                self.core.log.info(f"成功切换到显示器 {index}")
                self.update_state()
            else:
                self.core.log.error(f"错误: {data['message']}")
        except requests.exceptions.RequestException as e:
            self.core.log.error(f"请求失败: {e}")

    def handle_mqtt(self, entity, payload):
        self.change_monitor(int(payload))


    def update_state(self):
        self.core.mqtt.update_state_data(select_monitor, "FlaskApp_index", "number")