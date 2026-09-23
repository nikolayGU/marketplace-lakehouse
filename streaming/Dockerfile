FROM apache/spark:3.5.9-java17-python3

USER root

# Pinned jars, fetched at build time and checked against Maven Central's sha1, never at runtime.
# Kafka and pool versions follow spark-sql-kafka 3.5.9's pom; hadoop-aws matches the bundled
# Hadoop 3.3.4 and pulls in the aws-java-sdk-bundle it was built against.
ARG MAVEN=https://repo1.maven.org/maven2
RUN set -eux; \
    cd /opt/spark/jars; \
    for jar in \
      org/apache/iceberg/iceberg-spark-runtime-3.5_2.12/1.11.0/iceberg-spark-runtime-3.5_2.12-1.11.0.jar \
      org/apache/spark/spark-sql-kafka-0-10_2.12/3.5.9/spark-sql-kafka-0-10_2.12-3.5.9.jar \
      org/apache/spark/spark-token-provider-kafka-0-10_2.12/3.5.9/spark-token-provider-kafka-0-10_2.12-3.5.9.jar \
      org/apache/kafka/kafka-clients/3.4.1/kafka-clients-3.4.1.jar \
      org/apache/commons/commons-pool2/2.11.1/commons-pool2-2.11.1.jar \
      org/apache/hadoop/hadoop-aws/3.3.4/hadoop-aws-3.3.4.jar \
      com/amazonaws/aws-java-sdk-bundle/1.12.262/aws-java-sdk-bundle-1.12.262.jar \
      org/postgresql/postgresql/42.7.8/postgresql-42.7.8.jar; \
    do \
      name="$(basename "$jar")"; \
      curl -fsSL -o "$name" "$MAVEN/$jar"; \
      echo "$(curl -fsSL "$MAVEN/$jar.sha1")  $name" | sha1sum -c -; \
    done

RUN pip install --no-cache-dir \
    "pydantic-settings==2.15.0" \
    "prometheus-client==0.26.0"

COPY run-job.sh /opt/app/run-job.sh
COPY spark_jobs/ /opt/app/spark_jobs/
# contracts/ is outside this build context; compose and CI pass it as the named context `contracts`.
COPY --from=contracts silver/ /opt/app/contracts/silver/

ENV PYTHONPATH=/opt/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER spark
ENTRYPOINT ["/opt/app/run-job.sh"]
