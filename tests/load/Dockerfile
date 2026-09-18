FROM grafana/k6:2.2.0
COPY tests/load /tests/load
WORKDIR /tests/load
ENTRYPOINT ["k6"]
