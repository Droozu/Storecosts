import os

def main():
    print("Hello from Docker + Python!")
    print("ENV:", os.getenv("APP_ENV", "dev"))

if __name__ == "__main__":
    main()