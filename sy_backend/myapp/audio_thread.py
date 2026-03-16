# myapp/audio_thread.py
# 在apps.py中启动
# 在myapp/summarize_alarms_thread.py中通过设置cache"play_alert_sound"的值来控制声音播放
import os
import pygame
from django.core.cache import cache
from time import sleep

def audio_thread():
    # Initialize Pygame mixer
    try:
        pygame.mixer.init()
        print("Pygame mixer initialized")
    except pygame.error as e:
        print(f"Pygame mixer could not initialize: {e}")
        return

    audio_file_path = os.path.join(os.path.dirname(__file__), './static/myapp/audio/alert.mp3')

    while True:
        should_play = cache.get("play_alert_sound", False)
        if should_play:
            if not pygame.mixer.music.get_busy():
                pygame.mixer.music.load(audio_file_path)
                pygame.mixer.music.play()  # Play the sound once
            sleep(5)  # Sleep for 5 seconds to avoid constant replay
        else:
            sleep(2)  # Sleep for 2 seconds if not playing
