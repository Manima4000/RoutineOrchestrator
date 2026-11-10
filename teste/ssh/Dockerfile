FROM debian:12-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-server sudo tar rsync \
    && apt-get clean \
    && mkdir -p /run/sshd \
    && ssh-keygen -A \
    && useradd -m -s /bin/bash airflow-svc \
    && passwd -l airflow-svc \
    && echo 'airflow-svc ALL=(root) NOPASSWD: /bin/tar, /usr/bin/tar' > /etc/sudoers.d/airflow-svc \
    && chmod 440 /etc/sudoers.d/airflow-svc
EXPOSE 22
CMD ["/bin/bash", "-c", "install -d -m 700 -o airflow-svc -g airflow-svc /home/airflow-svc/.ssh && cat /chave_teste.pub /chaves-ambiente/id_ambiente.pub 2>/dev/null > /home/airflow-svc/.ssh/authorized_keys; chown airflow-svc:airflow-svc /home/airflow-svc/.ssh/authorized_keys && chmod 600 /home/airflow-svc/.ssh/authorized_keys && exec /usr/sbin/sshd -D -e -o PasswordAuthentication=no"]
