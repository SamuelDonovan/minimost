from minimost import create_app


def main():
    app = create_app()
    app.run(debug=False)


if __name__ == "__main__":
    main()
