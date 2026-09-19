from playwright.sync_api import sync_playwright


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        print(f"Chromium launched: {browser.version}")
        browser.close()


if __name__ == "__main__":
    main()
