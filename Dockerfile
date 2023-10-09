FROM debian

ARG VERSION="1.8.2"

WORKDIR /tmp

RUN apt update && apt install -y wget && dpkg --add-architecture i386 && apt install -y lib32z1 \
  && wget https://www.amxmodx.org/release/amxmodx-${VERSION}-base-linux.tar.gz \
  && wget https://www.amxmodx.org/release/amxmodx-${VERSION}-cstrike-linux.tar.gz \
  && wget https://www.amxmodx.org/release/amxmodx-${VERSION}-dod-linux.tar.gz \
  && wget https://www.amxmodx.org/release/amxmodx-${VERSION}-ns-linux.tar.gz \
  && wget https://www.amxmodx.org/release/amxmodx-${VERSION}-tfc-linux.tar.gz \
  && wget https://www.amxmodx.org/release/amxmodx-${VERSION}-ts-linux.tar.gz \
  && wget https://www.amxmodx.org/release/amxmodx-${VERSION}-esf-linux.tar.gz

RUN tar -zxf amxmodx-${VERSION}-base-linux.tar.gz \
  && tar -zxf amxmodx-${VERSION}-cstrike-linux.tar.gz \
  && tar -zxf amxmodx-${VERSION}-dod-linux.tar.gz \
  && tar -zxf amxmodx-${VERSION}-ns-linux.tar.gz \
  && tar -zxf amxmodx-${VERSION}-tfc-linux.tar.gz \
  && tar -zxf amxmodx-${VERSION}-ts-linux.tar.gz \
  && tar -zxf amxmodx-${VERSION}-esf-linux.tar.gz

RUN mv /tmp/addons/amxmodx/scripting /amxmodx \
  && rm -rf /app/addons /tmp/* /amxmodx/*.sma /amxmodx/amxmod_compat

ENV PATH="/amxmodx:${PATH}"
ENV LD_LIBRARY_PATH="/amxmodx:${LD_LIBRARY_PATH}"

COPY compile.sh /amxmodx/compile.sh

WORKDIR /app

ENTRYPOINT ["compile.sh"]
