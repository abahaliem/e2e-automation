from tests.demo_app.app import DEMO_PASSWORD, DEMO_USER, DemoServer


def main() -> None:
    server = DemoServer(port=5055)
    print(f"Aplikasi demo berjalan di {server.url}")
    print(f"Akun test: {DEMO_USER} / {DEMO_PASSWORD}")
    print("Tekan Ctrl+C untuk berhenti.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
