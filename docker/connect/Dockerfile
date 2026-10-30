FROM quay.io/debezium/connect:3.5@sha256:8ba4d73ded691f245d8a8ed66900e21a0878a22b2557cc354b9428743b17ab0f

# The entrypoint adds -javaagent:<jar>=9404:/kafka/config/metrics.yaml when
# ENABLE_JMX_EXPORTER=true, but the image ships no jar (W4-D1). 1.6.0 from the GitHub release:
# Maven Central stops at 1.0.1. The checksum is the release's own .sha256 file.
ADD --chown=kafka:kafka \
    --checksum=sha256:a95983fd96e865d2bcdf911cc500e7c82808c27ab9fd226bf96732b6c3d8c46e \
    https://github.com/prometheus/jmx_exporter/releases/download/1.6.0/jmx_prometheus_javaagent-1.6.0.jar \
    /kafka/libs/
COPY --chown=kafka:kafka metrics.yaml /kafka/config/metrics.yaml
