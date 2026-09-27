FROM alpine:3.20
RUN apk add --no-cache ffmpeg bash font-dejavu
WORKDIR /app
COPY gen.sh .
RUN chmod +x gen.sh
CMD ["bash", "/app/gen.sh"]
