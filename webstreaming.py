from flask import Response, Flask, render_template
from multiprocessing import Process, Manager
import time
import cv2
import logging

main_logger: logging.Logger = logging.getLogger("камера")
main_logger.setLevel(logging.INFO)
log_handler = logging.FileHandler("log.log", mode='w')
log_formatter = logging.Formatter("%(asctime)s %(message)s")
log_handler.setFormatter(log_formatter)
main_logger.addHandler(log_handler)

app: Flask = Flask(__name__)
source: str = "rtsp://admin:password@192.168.0.119:10554/tcp/av0_1"


def cache_frames(source: str, last_frame: list, running) -> None:
    """ Кэширование кадров """
    cap = cv2.VideoCapture(source)
    #cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # в некоторых случаях это позволяет избавится от старых кадров
    interval = 1 / cap.get(cv2.CAP_PROP_FPS) + 3  # Интервал между кадрами
    while running.value:
        ret, frame = cap.read()  # Чтение кадра
        if ret:  # Если кадр считан
           #frame = cv2.resize(frame, (640, 360))  # Изменение размера кадра, по необходимости
            _, buffer = cv2.imencode('.jpg', frame,
                                     [int(cv2.IMWRITE_JPEG_QUALITY), 85])  # Кодирование кадра в JPEG
            last_frame[0] = buffer.tobytes()  # Кэширование кадра
            time.sleep(interval)
        else:
            # Если не удалось захватить кадр
            main_logger.error("Не удалось захватить кадр, попробуйте проверить источник видеопотока.")
            cap.release()
            time.sleep(2)
            cap = cv2.VideoCapture(source)  # Повторное открытие камеры
    cap.release()


def generate(shared_last_frame: list):
    """ Генератор кадров """
    frame_data = None
    while True:
        if frame_data != shared_last_frame[0]:  # Если кадр изменился
            frame_data = shared_last_frame[0]
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_data + b'\r\n')  # HTTP ответ для потоковой передачи
        time.sleep(1/15)  # Задержка


@app.route("/")
def index() -> str:
    # Возвращаем отрендеренный шаблон
    return render_template("index.html")


@app.route("/video_feed")
def video_feed() -> Response:
    return Response(generate(last_frame),
                    mimetype="multipart/x-mixed-replace; boundary=frame")  # Запуск генератора


if __name__ == '__main__':
    with Manager() as manager:
        last_frame = manager.list([None])  # Кэш последнего кадра
        running = manager.Value('i', 1)  # Управляемый флаг для контроля выполнения процесса

        # Создаём процесс для кэширования кадров
        p = Process(target=cache_frames, args=(source, last_frame, running))
        p.start()

        # Запуск Flask-приложения в блоке try/except
        try:
            app.run(host='0.0.0.0', port=8000, debug=False, threaded=True, use_reloader=False)
        except KeyboardInterrupt:
            p.join()  # Ожидаем завершения процесса
        finally:
            running.value = 0  # Устанавливаем флаг в 0, сигнализируя процессу о необходимости завершения

        p.terminate()  # Принудительно завершаем процесс, если он все еще выполняется
        p.join()  # Убедимся, что процесс завершился
