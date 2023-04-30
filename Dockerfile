FROM ubuntu:22.04

RUN apt-get update && \
    apt-get install -y git zip unzip openjdk-17-jdk python3-pip autoconf libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo5 cmake libffi-dev libssl-dev

RUN useradd -ms /bin/bash u
USER u

RUN pip3 install "kivy[full]" yt-dlp Cython==0.29.33 buildozer

RUN echo "export PATH=$PATH:~/.local/bin/" >> ~/.bashrc

WORKDIR /app