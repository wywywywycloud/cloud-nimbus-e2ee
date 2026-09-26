FROM golang:1.23-alpine AS build

WORKDIR /src
COPY go.mod ./
COPY cmd ./cmd
COPY internal ./internal
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/storage-gateway ./cmd/storage-gateway \
    && mkdir -p /out/data \
    && chown -R 65532:65532 /out/data

FROM scratch
COPY --from=build /out/storage-gateway /storage-gateway
COPY --from=build --chown=65532:65532 /out/data /data
USER 65532:65532
ENV ADDRESS=:8080 STORAGE_ROOT=/data
EXPOSE 8080
VOLUME ["/data"]
ENTRYPOINT ["/storage-gateway"]
