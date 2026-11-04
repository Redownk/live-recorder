"""提供媒体子进程的输出采集和退出回收能力。"""

import asyncio


async def stop_process(process, timeout=5):
    """终止并回收子进程，宽限期结束后强制退出。

    Args:
        process: 异步子进程，允许为 None 或已退出的进程。
        timeout: 等待正常退出的秒数。
    """
    if process is None or process.returncode is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        await process.wait()


async def capture_output(*command, timeout=30, error_message="命令执行失败"):
    """采集命令输出，在超时、取消或执行结束时回收子进程。

    Args:
        *command: 可执行文件及命令参数。
        timeout: 输出采集的最长等待秒数。
        error_message: 命令失败且没有错误输出时使用的说明。

    Returns:
        标准输出的原始字节。

    Raises:
        ValueError: 子进程返回非零退出码。
        TimeoutError: 输出采集超时。
        OSError: 无法启动子进程。
    """
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
        if process.returncode:
            raise ValueError(stderr.decode("utf-8", errors="replace")[-2000:] or error_message)
        return stdout
    finally:
        await stop_process(process)
