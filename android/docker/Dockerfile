FROM eclipse-temurin:17-jdk-jammy

ARG ANDROID_CMDLINE_TOOLS_VERSION=15859902
ARG ANDROID_CMDLINE_TOOLS_SHA256=4e4c464f145a7512b57d088ac6c278c03c9eea610886b35a5e0804e74eedf583
ARG ANDROID_PLATFORM=36
ARG ANDROID_BUILD_TOOLS=36.0.0
ARG GRADLE_VERSION=9.6.0

ENV DEBIAN_FRONTEND=noninteractive \
    ANDROID_SDK_ROOT=/opt/android-sdk \
    ANDROID_HOME=/opt/android-sdk \
    GRADLE_HOME=/opt/gradle/gradle-9.6.0 \
    GRADLE_USER_HOME=/gradle-cache
ENV PATH="${PATH}:${ANDROID_SDK_ROOT}/cmdline-tools/latest/bin:${ANDROID_SDK_ROOT}/platform-tools:${GRADLE_HOME}/bin"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates=20260601~22.04.1 \
       curl=7.81.0-1ubuntu1.27 \
       unzip=6.0-26ubuntu3.2 \
       git=1:2.34.1-1ubuntu1.17 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/android-sdk/cmdline-tools /tmp/android-tools \
    && curl -fsSL --retry 5 --retry-delay 2 \
       "https://dl.google.com/android/repository/commandlinetools-linux-${ANDROID_CMDLINE_TOOLS_VERSION}_latest.zip" \
       -o /tmp/android-tools/tools.zip \
    && echo "${ANDROID_CMDLINE_TOOLS_SHA256}  /tmp/android-tools/tools.zip" | sha256sum -c - \
    && unzip -q /tmp/android-tools/tools.zip -d /tmp/android-tools/extracted \
    && mkdir -p /opt/android-sdk/cmdline-tools/latest \
    && mv /tmp/android-tools/extracted/cmdline-tools/* /opt/android-sdk/cmdline-tools/latest/ \
    && rm -rf /tmp/android-tools \
    && command -v android \
    && android --version

# sdkmanager is deprecated in the current command-line tools. Use Android CLI.
# API 36 is the current stable SDK platform; AGP 9.4 supports it (and up to 37).
RUN yes | android --sdk="${ANDROID_SDK_ROOT}" sdk install \
       "platform-tools" \
       "platforms/android-${ANDROID_PLATFORM}" \
       "build-tools/${ANDROID_BUILD_TOOLS}" \
    && test -f "${ANDROID_SDK_ROOT}/platforms/android-${ANDROID_PLATFORM}/android.jar" \
    && test -x "${ANDROID_SDK_ROOT}/build-tools/${ANDROID_BUILD_TOOLS}/aapt2" \
    && "${ANDROID_SDK_ROOT}/platform-tools/adb" version \
    && "${ANDROID_SDK_ROOT}/build-tools/${ANDROID_BUILD_TOOLS}/aapt2" version

RUN mkdir -p /opt/gradle /tmp/gradle \
    && curl -fsSL --retry 5 --retry-delay 2 \
       "https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip" \
       -o /tmp/gradle/gradle.zip \
    && curl -fsSL --retry 5 --retry-delay 2 \
       "https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip.sha256" \
       -o /tmp/gradle/gradle.sha256 \
    && echo "$(cat /tmp/gradle/gradle.sha256)  /tmp/gradle/gradle.zip" | sha256sum -c - \
    && unzip -q /tmp/gradle/gradle.zip -d /opt/gradle \
    && rm -rf /tmp/gradle \
    && gradle --version

WORKDIR /workspace/android
CMD ["bash"]
