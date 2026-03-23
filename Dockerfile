FROM ubuntu:22.04

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends \
        gcc-arm-none-eabi \
        binutils-arm-none-eabi \
        cmake \
        ninja-build \
        python3 \
        python3-pip \
        cppcheck \
        git \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Verify toolchain is functional
RUN arm-none-eabi-gcc --version && cmake --version && ninja --version

WORKDIR /workspace

# Copy project sources (respects .dockerignore)
COPY . .

# Default: build Release firmware
# Override with: docker run --rm -v $(pwd)/build:/workspace/build <image> cmake --preset Debug
CMD ["sh", "-c", "cmake --preset Release && cmake --build build/Release --parallel"]
