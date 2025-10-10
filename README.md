# Outline RAG v2

This document provides an overview of the Outline RAG v2 project, its structure, and how to get it running.

---

[English](#outline-rag-v2-english) | [中文](#outline-rag-v2-中文)

---

## Outline RAG v2 (English)

### 1. Overview

This project is a web application that implements a Retrieval-Augmented Generation (RAG) system. It uses a Python backend with the Flask framework to provide a web interface for interacting with the RAG model.


### 2. Getting Started

#### Installation & Running

1.  **Clone the repository:**
    ```bash
    git clone <your-repository-url>
    cd outline-rag-v2
    ```

2.  **Create and activate a virtual environment:**
    ```bash
    # For macOS/Linux
    python3 -m venv venv
    source venv/bin/activate

    # For Windows
    python -m venv venv
    .\venv\Scripts\activate
    ```

3.  **Install the dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Run the application:**
    ```bash
    python app.py
    ```
    The application will be available at `http://127.0.0.1:5000`.

### 4. Deployment with Docker

This project includes a `Dockerfile` for easy containerization.

1.  **Build the Docker image:**
    ```bash
    docker build -t outline-rag-v2 .
    ```

2.  **Run the Docker container:**
    ```bash
    docker run -p 5000:5000 outline-rag-v2
    ```

---

## Outline RAG v2 (中文)

### 1. 项目概述

本项目是一个实现了检索增强生成（RAG）系统的 Web 应用程序。它使用 Python 的 Flask 框架作为后端，为 RAG 模型提供了一个可交互的 Web 界面。


### 2. 快速开始

#### 安装与运行

1.  **克隆仓库：**
    ```bash
    git clone <your-repository-url>
    cd outline-rag-v2
    ```

2.  **创建并激活虚拟环境：**
    ```bash
    # macOS/Linux
    python3 -m venv venv
    source venv/bin/activate

    # Windows
    python -m venv venv
    .\venv\Scripts\activate
    ```

3.  **安装依赖：**
    ```bash
    pip install -r requirements.txt
    ```

4.  **运行应用：**
    ```bash
    python app.py
    ```
    应用将在 `http://127.0.0.1:5000` 上运行。

### 4. 使用 Docker 部署

项目包含一个 `Dockerfile` 以方便容器化部署。

1.  **构建 Docker 镜像：**
    ```bash
    docker build -t outline-rag-v2 .
    ```

2.  **运行 Docker 容器：**
    ```bash
    docker run -p 5000:5000 outline-rag-v2
    ```