from app.service import OrderService, archive


def nightly_cleanup():
    OrderService().purge_old(90)
    archive("exports")


if __name__ == "__main__":
    nightly_cleanup()
