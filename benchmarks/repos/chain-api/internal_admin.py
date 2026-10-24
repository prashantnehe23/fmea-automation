import shutil

from flask import Flask

admin = Flask(__name__)
# Listens on 127.0.0.1:9000, so it is only reachable from the host itself.


@admin.get("/wipe-backups")
def wipe_backups():
    shutil.rmtree("/var/backups/shop", ignore_errors=True)
    return "done"


if __name__ == "__main__":
    admin.run(host="127.0.0.1", port=9000)
