# Release tag from github.com/alliedmodders/amxmodx/releases, see latest-version.sh
ARG VERSION

# Download and unpack on Debian; only scripting/ and the compiler's runtime
# libraries are copied into the final image
FROM debian:trixie-slim AS fetch
ARG VERSION
RUN apt-get update && apt-get install -y --no-install-recommends wget ca-certificates \
  && cd /tmp && for mod in base cstrike dod ns tfc ts esf; do \
    wget -q https://github.com/alliedmodders/amxmodx/releases/download/${VERSION}/amxmodx-${VERSION%.*}-git${VERSION##*.}-${mod}-linux.tar.gz \
    && tar -zxf amxmodx-${VERSION%.*}-git${VERSION##*.}-${mod}-linux.tar.gz || exit 1; \
  done \
  && mv /tmp/addons/amxmodx/scripting /amxmodx \
  && rm -rf /amxmodx/*.sma /amxmodx/amxmod_compat /amxmodx/testsuite
# amxxpc is a 32-bit glibc binary; these are exactly the files its loader opens
# for amxxpc and amxxpc32.so (ld-linux.so.2 --list, LD_DEBUG=files)
RUN dpkg --add-architecture i386 && apt-get update \
  && apt-get install -y --no-install-recommends lib32stdc++6 \
  && mkdir -p /glibc32 \
  && cd /usr/lib32 && cp -L ld-linux.so.2 libc.so.6 libdl.so.2 libm.so.6 libpthread.so.0 libstdc++.so.6 libgcc_s.so.1 /glibc32/

FROM alpine
RUN apk add --no-cache python3 bash
# The 32-bit glibc runtime stays off the musl search path; only the amxxpc
# wrapper points the glibc loader at it
COPY --from=fetch /glibc32 /usr/lib32
COPY --from=fetch /amxmodx /amxmodx
RUN mv /amxmodx/amxxpc /amxmodx/amxxpc.bin \
  && printf '#!/bin/sh\nexec /usr/lib32/ld-linux.so.2 --library-path /amxmodx:/usr/lib32 /amxmodx/amxxpc.bin "$@"\n' > /amxmodx/amxxpc \
  && chmod +x /amxmodx/amxxpc
ENV PATH="/amxmodx:${PATH}"
COPY compile.sh lint.sh amxxci.py /amxmodx/
# Fails the build if Python or the compiler cannot start
RUN python3 /amxmodx/amxxci.py --help > /dev/null && amxxpc 2>&1 | grep -q "AMX Mod X Compiler"
WORKDIR /app
ENTRYPOINT ["compile.sh"]
