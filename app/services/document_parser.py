from pathlib import Path

try:
    import pypdf
except ImportError:
    pypdf = None


class DocumentParserService:
    """文档解析服务，支持 PDF, Markdown, TXT 格式。"""

    @staticmethod
    def parse_pdf(file_path: str | Path) -> str:
        """解析 PDF 文件。

        Args:
            file_path: PDF 文件路径

        Returns:
            str: 提取的文本

        Raises:
            ImportError: 如果未安装 pypdf
            ValueError: 如果 PDF 格式错误
        """
        if pypdf is None:
            raise ImportError("pypdf is not installed. Install it with: pip install pypdf")

        try:
            text = ""
            with open(file_path, "rb") as f:
                reader = pypdf.PdfReader(f)
                for page_num, page in enumerate(reader.pages):
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text
                    # 在页面之间添加分隔符
                    if page_num < len(reader.pages) - 1:
                        text += "\n--- Page Break ---\n"
            return text.strip()
        except Exception as e:
            raise ValueError(f"Failed to parse PDF: {e}")

    @staticmethod
    def parse_markdown(file_path: str | Path) -> str:
        """解析 Markdown 文件。

        Args:
            file_path: Markdown 文件路径

        Returns:
            str: 文件内容

        Raises:
            ValueError: 如果文件格式错误
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except UnicodeDecodeError as e:
            raise ValueError(f"Failed to decode Markdown file: {e}")
        except Exception as e:
            raise ValueError(f"Failed to parse Markdown: {e}")

    @staticmethod
    def parse_txt(file_path: str | Path) -> str:
        """解析 TXT 文件。

        Args:
            file_path: TXT 文件路径

        Returns:
            str: 文件内容

        Raises:
            ValueError: 如果文件格式错误
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except UnicodeDecodeError as e:
            raise ValueError(f"Failed to decode TXT file: {e}")
        except Exception as e:
            raise ValueError(f"Failed to parse TXT: {e}")

    @staticmethod
    def parse(file_path: str | Path, source_type: str) -> str:
        """根据文件类型解析文件。

        Args:
            file_path: 文件路径
            source_type: 文件类型 (pdf, markdown, txt)

        Returns:
            str: 提取的文本

        Raises:
            ValueError: 如果文件类型不支持或解析失败
        """
        source_type = source_type.lower()

        if source_type == "pdf":
            return DocumentParserService.parse_pdf(file_path)
        elif source_type in ("markdown", "md"):
            return DocumentParserService.parse_markdown(file_path)
        elif source_type == "txt":
            return DocumentParserService.parse_txt(file_path)
        else:
            raise ValueError(f"Unsupported file type: {source_type}")
