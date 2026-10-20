# Official MIT Battlecode engine; pinned source, Java 21 and Python 3.12.
# Build from the repository root: docker build -f integrations/battlecode26/Dockerfile -t neon-arena-battlecode:2026 .
FROM gradle:8.10-jdk21 AS engine
ADD --checksum=sha256:bb0bab34c26a60d423bbb5d1a0e55ab28d9ee31a76780ef314161c41b4ffc696 https://codeload.github.com/battlecode/battlecode26/zip/103abf6b67a2cf544e6344dddef9318af9ae9193 /tmp/battlecode.zip
WORKDIR /src
RUN jar xf /tmp/battlecode.zip
WORKDIR /src/battlecode26-103abf6b67a2cf544e6344dddef9318af9ae9193
RUN gradle --no-daemon :engine:jar

FROM eclipse-temurin:21-jdk-jammy AS jdk
FROM python:3.12-slim-bookworm AS runtime
COPY --from=jdk /opt/java/openjdk /opt/java/openjdk
ENV JAVA_HOME=/opt/java/openjdk
ENV PATH="/opt/java/openjdk/bin:${PATH}"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY --from=engine /src/battlecode26-103abf6b67a2cf544e6344dddef9318af9ae9193/engine/build/libs/*.jar /opt/battlecode/engine.jar
COPY --from=engine /src/battlecode26-103abf6b67a2cf544e6344dddef9318af9ae9193/engine/src/crossplay_python /opt/battlecode/python
RUN pip install --no-cache-dir /opt/battlecode/python
COPY integrations/battlecode26/ArenaReplay.java integrations/battlecode26/driver.py /opt/arena/
RUN javac -cp /opt/battlecode/engine.jar -d /opt/arena /opt/arena/ArenaReplay.java
RUN groupadd -g 10001 arena && useradd -u 10001 -g 10001 -M arena
WORKDIR /work
USER 10001:10001
CMD ["python", "-c", "import time; time.sleep(86400)"]
