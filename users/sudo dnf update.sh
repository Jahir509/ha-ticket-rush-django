sudo dnf update
sudo dnf install -y postgresql-common
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh


scp ca.crt etcd-node1.crt etcd-node1.key syslogon@10.2.116.112:/tmp/
scp ca.crt etcd-node2.crt etcd-node2.key rocky@10.2.115.110:/tmp/
scp ca.crt etcd-node3.crt etcd-node3.key syslogon@10.2.116.130:/tmp/




# // node 01
ETCD_NAME="postgresql-01"
ETCD_DATA_DIR="/var/lib/etcd"
ETCD_INITIAL_CLUSTER="postgresql-01=https://10.2.116.112:2380,postgresql-02=https://10.2.115.110:2380,postgresql-03=https://10.2.116.130:2380"
ETCD_INITIAL_CLUSTER_STATE="new"
ETCD_INITIAL_CLUSTER_TOKEN="etcd-cluster"
ETCD_INITIAL_ADVERTISE_PEER_URLS="https://10.2.116.112:2380"
ETCD_LISTEN_PEER_URLS="https://0.0.0.0:2380"
ETCD_LISTEN_CLIENT_URLS="https://0.0.0.0:2379"
ETCD_ADVERTISE_CLIENT_URLS="https://10.2.116.112:2379"
ETCD_CLIENT_CERT_AUTH="true"
ETCD_TRUSTED_CA_FILE="/etc/etcd/ssl/ca.crt"
ETCD_CERT_FILE="/etc/etcd/ssl/etcd-node1.crt"
ETCD_KEY_FILE="/etc/etcd/ssl/etcd-node1.key"
ETCD_PEER_CLIENT_CERT_AUTH="true"
ETCD_PEER_TRUSTED_CA_FILE="/etc/etcd/ssl/ca.crt"
ETCD_PEER_CERT_FILE="/etc/etcd/ssl/etcd-node1.crt"
ETCD_PEER_KEY_FILE="/etc/etcd/ssl/etcd-node1.key"



# node 02
ETCD_NAME="postgresql-02"
ETCD_DATA_DIR="/var/lib/etcd"
ETCD_INITIAL_CLUSTER="postgresql-01=https://10.2.116.112:2380,postgresql-02=https://10.2.115.110:2380,postgresql-03=https://10.2.116.130:2380"
ETCD_INITIAL_CLUSTER_STATE="new"
ETCD_INITIAL_CLUSTER_TOKEN="etcd-cluster"
ETCD_INITIAL_ADVERTISE_PEER_URLS="https://10.2.115.110:2380"
ETCD_LISTEN_PEER_URLS="https://0.0.0.0:2380"
ETCD_LISTEN_CLIENT_URLS="https://0.0.0.0:2379"
ETCD_ADVERTISE_CLIENT_URLS="https://10.2.115.110:2379"
ETCD_CLIENT_CERT_AUTH="true"
ETCD_TRUSTED_CA_FILE="/etc/etcd/ssl/ca.crt"
ETCD_CERT_FILE="/etc/etcd/ssl/etcd-node2.crt"
ETCD_KEY_FILE="/etc/etcd/ssl/etcd-node2.key"
ETCD_PEER_CLIENT_CERT_AUTH="true"
ETCD_PEER_TRUSTED_CA_FILE="/etc/etcd/ssl/ca.crt"
ETCD_PEER_CERT_FILE="/etc/etcd/ssl/etcd-node2.crt"
ETCD_PEER_KEY_FILE="/etc/etcd/ssl/etcd-node2.key"


# node 03
ETCD_NAME="postgresql-03"
ETCD_DATA_DIR="/var/lib/etcd"
ETCD_INITIAL_CLUSTER="postgresql-01=https://10.2.116.112:2380,postgresql-02=https://10.2.115.110:2380,postgresql-03=https://10.2.116.130:2380"
ETCD_INITIAL_CLUSTER_STATE="new"
ETCD_INITIAL_CLUSTER_TOKEN="etcd-cluster"
ETCD_INITIAL_ADVERTISE_PEER_URLS="https://10.2.116.130:2380"
ETCD_LISTEN_PEER_URLS="https://0.0.0.0:2380"
ETCD_LISTEN_CLIENT_URLS="https://0.0.0.0:2379"
ETCD_ADVERTISE_CLIENT_URLS="https://10.2.116.130:2379"
ETCD_CLIENT_CERT_AUTH="true"
ETCD_TRUSTED_CA_FILE="/etc/etcd/ssl/ca.crt"
ETCD_CERT_FILE="/etc/etcd/ssl/etcd-node3.crt"
ETCD_KEY_FILE="/etc/etcd/ssl/etcd-node3.key"
ETCD_PEER_CLIENT_CERT_AUTH="true"
ETCD_PEER_TRUSTED_CA_FILE="/etc/etcd/ssl/ca.crt"
ETCD_PEER_CERT_FILE="/etc/etcd/ssl/etcd-node3.crt"
ETCD_PEER_KEY_FILE="/etc/etcd/ssl/etcd-node3.key"




# 
sudo /usr/local/bin/etcdctl \
  --endpoints=https://10.2.116.112:2379,https://10.2.115.110:2379,https://10.2.116.130:2379 \
  --cacert=/etc/etcd/ssl/ca.crt \
  --cert=/etc/etcd/ssl/etcd-node1.crt \
  --key=/etc/etcd/ssl/etcd-node1.key \
  endpoint status --write-out=table




scp server.crt server.key server.req syslogon@10.2.116.112:/tmp
scp server.crt server.key server.req rocky@10.2.115.110:/tmp
scp server.crt server.key server.req syslogon@10.2.116.130:/tmp


sudo dnf update
sudo dnf install -y acl







# node01

scope: postgresql-cluster
namespace: /service/
name: postgresql-01  # node1

etcd3:
  hosts: 10.2.116.112:2379,10.2.115.110:2379,10.2.116.130:2379  # etcd cluster nodes
  protocol: https
  cacert: /etc/etcd/ssl/ca.crt
  cert: /etc/etcd/ssl/etcd-node1.crt  # node1's etcd certificate
  key: /etc/etcd/ssl/etcd-node1.key  # node1's etcd key

restapi:
  listen: 0.0.0.0:8008
  connect_address: 10.2.116.112:8008  # IP for node1's REST API
  certfile: /var/lib/pgsql/ssl/server.pem

bootstrap:
  dcs:
    ttl: 30
    loop_wait: 10
    retry_timeout: 10
    maximum_lag_on_failover: 1048576  # Failover parameters
    postgresql:
        parameters:
            ssl: 'on'  # Enable SSL
            ssl_cert_file: /var/lib/pgsql/ssl/server.crt  # PostgreSQL server certificate
            ssl_key_file: /var/lib/pgsql/ssl/server.key  # PostgreSQL server key
        pg_hba:  # Access rules
        - hostssl replication replicator 127.0.0.1/32 md5
        - hostssl replication replicator 10.2.116.112/32 md5
        - hostssl replication replicator 10.2.115.110/32 md5
        - hostssl replication replicator 10.2.116.130/32 md5
        - hostssl all all 127.0.0.1/32 md5
        - hostssl all all 0.0.0.0/0 md5
  initdb:
    - encoding: UTF8
    - data-checksums

postgresql:
  listen: 0.0.0.0:5432
  connect_address: 10.2.116.112:5432  # IP for node1's PostgreSQL
  data_dir: /var/lib/pgsql/16/data
  bin_dir: /usr/bin  # Binary directory for PostgreSQL 17
  authentication:
    superuser:
      username: postgres
      password: cnV2abjbDpbh64e12987wR4mj5kQ3456Y0Qf  # Superuser password - be sure to change
    replication:
      username: replicator
      password: sad9a23jga8jsuedrwtsskj74567suiuwe23  # Replication password - be sure to change
  parameters:
    max_connections: 100
    shared_buffers: 256MB

tags:
  nofailover: false
  noloadbalance: false
  clonefrom: false



# node 02

scope: postgresql-cluster
namespace: /service/
name: postgresql-02  # Unique name for Node 2

etcd3:
  hosts: 10.2.116.112:2379,10.2.115.110:2379,10.2.116.130:2379  # etcd cluster nodes
  protocol: https
  cacert: /etc/etcd/ssl/ca.crt
  cert: /etc/etcd/ssl/etcd-node2.crt  # Node 2's etcd certificate
  key: /etc/etcd/ssl/etcd-node2.key  # Node 2's etcd key

restapi:
  listen: 0.0.0.0:8008
  connect_address: 10.2.115.110:8008  # IP for Node 2's REST API
  certfile: /var/lib/pgsql/ssl/server.pem

bootstrap:
  dcs:
    ttl: 30
    loop_wait: 10
    retry_timeout: 10
    maximum_lag_on_failover: 1048576
    postgresql:
        parameters:
        ssl: 'on'
        ssl_cert_file: /var/lib/pgsql/ssl/server.crt
        ssl_key_file: /var/lib/pgsql/ssl/server.key
        pg_hba:
        - hostssl replication replicator 127.0.0.1/32 md5
        - hostssl replication replicator 10.2.116.112/32 md5
        - hostssl replication replicator 10.2.115.110/32 md5
        - hostssl replication replicator 10.2.116.130/32 md5
        - hostssl all all 127.0.0.1/32 md5
        - hostssl all all 0.0.0.0/0 md5
  initdb:
    - encoding: UTF8
    - data-checksums

postgresql:
  listen: 0.0.0.0:5432
  connect_address: 10.2.115.110:5432  # IP for Node 2's PostgreSQL
  data_dir: /var/lib/pgsql/16/data
  bin_dir: /usr/bin
  authentication:
    superuser:
      username: postgres
      password: cnV2abjbDpbh64e12987wR4mj5kQ3456Y0Qf  # Superuser password (provided)
    replication:
      username: replicator
      password: sad9a23jga8jsuedrwtsskj74567suiuwe23  # Replication password (provided)
  parameters:
    max_connections: 100
    shared_buffers: 256MB

tags:
  nofailover: false
  noloadbalance: false
  clonefrom: false



# node 03
scope: postgresql-cluster
namespace: /service/
name: postgresql-03  # Unique name for Node 3

etcd3:
  hosts: 10.2.116.112:2379,10.2.115.110:2379,10.2.116.130:2379 #etcd cluster nodes
  protocol: https
  cacert: /etc/etcd/ssl/ca.crt
  cert: /etc/etcd/ssl/etcd-node3.crt  # Node 3's etcd certificate
  key: /etc/etcd/ssl/etcd-node3.key  # Node 3's etcd key

restapi:
  listen: 0.0.0.0:8008
  connect_address: 10.2.116.130:8008  # IP for Node 3's REST API
  certfile: /var/lib/pgsql/ssl/server.pem

bootstrap:
  dcs:
    ttl: 30
    loop_wait: 10
    retry_timeout: 10
    maximum_lag_on_failover: 1048576
    postgresql:
        parameters:
        ssl: 'on'
        ssl_cert_file: /var/lib/pgsql/ssl/server.crt
        ssl_key_file: /var/lib/pgsql/ssl/server.key
        pg_hba:
        - hostssl replication replicator 127.0.0.1/32 md5
        - hostssl replication replicator 10.2.116.112/32 md5
        - hostssl replication replicator 10.2.115.110/32 md5
        - hostssl replication replicator 10.2.116.130/32 md5
        - hostssl all all 127.0.0.1/32 md5
        - hostssl all all 0.0.0.0/0 md5
  initdb:
    - encoding: UTF8
    - data-checksums

postgresql:
  listen: 0.0.0.0:5432
  connect_address: 10.2.116.130:5432  # IP for Node 3's PostgreSQL
  data_dir: /var/lib/pgsql/16/data
  bin_dir: /usr/bin
  authentication:
    superuser:
      username: postgres
      password: "cnV2abjbDpbh64e12987wR4mj5kQ3456Y0Qf"  # Superuser password (provided)
    replication:
      username: replicator
      password: sad9a23jga8jsuedrwtsskj74567suiuwe23  # Replication password (provided)
  parameters:
    max_connections: 100
    shared_buffers: 256MB

tags:
  nofailover: false
  noloadbalance: false
  clonefrom: false



# 

curl -k https://10.2.116.112:8008/primary
curl -k https://10.2.115.110:8008/primary
curl -k https://10.2.116.130:8008/primary