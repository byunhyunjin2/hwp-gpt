# 오픈소스 고지 (Third-Party Notices)

HWP_GPT 설치본에는 아래 구성요소가 포함되어 있습니다. 각 구성요소의 저작권은 해당 저작자에게 있습니다.

| 구성요소 | 용도 | 라이선스 | 출처 |
|---|---|---|---|
| OpenAI Codex CLI `rust-v0.163.0` (`codex/` 폴더) | ChatGPT 로그인·대화 실행 | Apache License 2.0 | https://github.com/openai/codex |
| Python 3.14 런타임 | 실행 환경 | PSF License | https://www.python.org |
| pywebview 6.2.1 | 패널 화면(WebView2) | BSD 3-Clause | https://github.com/r0x0r/pywebview |
| pythonnet 3.2.1 | pywebview의 .NET 연결 | MIT | https://github.com/pythonnet/pythonnet |
| pywin32 | 한글 COM 자동화·창 제어 | PSF License | https://github.com/mhammond/pywin32 |
| MCP Python SDK (`mcp`) | 도구 서버 | MIT | https://github.com/modelcontextprotocol/python-sdk |
| Microsoft Edge WebView2 Runtime | 패널 화면 표시 (Windows 기본 제공, 동봉 안 함) | Microsoft 소프트웨어 사용 조건 | https://developer.microsoft.com/microsoft-edge/webview2/ |

Codex CLI는 OpenAI의 공식 릴리스 바이너리를 수정 없이 동봉하며, 동봉 전 SHA256(릴리스 게시값)과 OpenAI 코드 서명을 확인했습니다.
Apache License 2.0 전문: https://www.apache.org/licenses/LICENSE-2.0

HWP_GPT는 한글과컴퓨터의 공식 제품이 아니며 한컴과 관련이 없습니다. "한글", "HWP"는 해당 권리자의 상표일 수 있습니다.
