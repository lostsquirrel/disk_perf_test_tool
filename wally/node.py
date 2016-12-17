import os
import time
import json
import socket
import logging
import subprocess
from typing import Union, cast, Any, Optional, Tuple, Dict, List


import agent
import paramiko


from .node_interfaces import IRPCNode, NodeInfo, ISSHHost
from .ssh import connect as ssh_connect


logger = logging.getLogger("wally")


class SSHHost(ISSHHost):
    def __init__(self, conn: paramiko.SSHClient, info: NodeInfo) -> None:
        self.conn = conn
        self.info = info

    def __str__(self) -> str:
        return self.info.node_id()

    def put_to_file(self, path: Optional[str], content: bytes) -> str:
        if path is None:
            path = self.run("mktemp").strip()

        with self.conn.open_sftp() as sftp:
            with sftp.open(path, "wb") as fd:
                fd.write(content)

        return path

    def disconnect(self):
        self.conn.close()

    def run(self, cmd: str, timeout: int = 60, nolog: bool = False) -> str:
        transport = self.conn.get_transport()
        session = transport.open_session()

        try:
            session.set_combine_stderr(True)

            stime = time.time()

            if not nolog:
                logger.debug("SSH:{0} Exec {1!r}".format(self, cmd))

            session.exec_command(cmd)
            session.settimeout(1)
            session.shutdown_write()
            output = ""

            while True:
                try:
                    ndata = session.recv(1024).decode("utf-8")
                    if not ndata:
                        break
                    output += ndata
                except socket.timeout:
                    pass

                if time.time() - stime > timeout:
                    raise OSError(output + "\nExecution timeout")

            code = session.recv_exit_status()
        finally:
            found = False

            if found:
                session.close()

        if code != 0:
            templ = "SSH:{0} Cmd {1!r} failed with code {2}. Output: {3}"
            raise OSError(templ.format(self, cmd, code, output))

        return output


class LocalHost(ISSHHost):
    def __str__(self):
        return "<Local>"

    def get_ip(self) -> str:
        return 'localhost'

    def put_to_file(self, path: str, content: bytes) -> None:
        dir_name = os.path.dirname(path)
        os.makedirs(dir_name, exist_ok=True)

        with open(path, "wb") as fd:
            fd.write(content)

    def run(self, cmd: str, timeout: int = 60, nolog: bool = False) -> str:
        proc = subprocess.Popen(cmd, shell=True,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)

        stdout_data_b, _ = proc.communicate()
        stdout_data = stdout_data_b.decode("utf8")

        if proc.returncode != 0:
            templ = "SSH:{0} Cmd {1!r} failed with code {2}. Output: {3}"
            raise OSError(templ.format(self, cmd, proc.returncode, stdout_data))

        return stdout_data

    def disconnect(self):
        pass


def get_rpc_server_code() -> Tuple[bytes, Dict[str, bytes]]:
    # setup rpc data
    if agent.__file__.endswith(".pyc"):
        path = agent.__file__[:-1]
    else:
        path = agent.__file__

    master_code = open(path, "rb").read()

    plugins = {}  # type: Dict[str, bytes]
    cli_path = os.path.join(os.path.dirname(path), "cli_plugin.py")
    plugins["cli"] = open(cli_path, "rb").read()

    fs_path = os.path.join(os.path.dirname(path), "fs_plugin.py")
    plugins["fs"] = open(fs_path, "rb").read()

    return master_code, plugins


def connect(info: Union[str, NodeInfo], conn_timeout: int = 60) -> ISSHHost:
    if info == 'local':
        return LocalHost()
    else:
        info_c = cast(NodeInfo, info)
        return SSHHost(ssh_connect(info_c.ssh_creds, conn_timeout), info_c)


class RPCNode(IRPCNode):
    """Node object"""

    def __init__(self, conn: agent.SimpleRPCClient, info: NodeInfo) -> None:
        self.info = info
        self.conn = conn

    def __str__(self) -> str:
        return "Node(url={!r}, roles={!r})".format(self.info.ssh_creds, ",".join(self.info.roles))

    def __repr__(self) -> str:
        return str(self)

    def get_file_content(self, path: str) -> bytes:
        raise NotImplementedError()

    def run(self, cmd: str, timeout: int = 60, nolog: bool = False) -> str:
        raise NotImplementedError()

    def copy_file(self, local_path: str, remote_path: str = None) -> str:
        raise NotImplementedError()

    def put_to_file(self, path: Optional[str], content: bytes) -> str:
        raise NotImplementedError()

    def get_interface(self, ip: str) -> str:
        raise NotImplementedError()

    def stat_file(self, path: str) -> Any:
        raise NotImplementedError()

    def disconnect(self) -> str:
        self.conn.disconnect()
        self.conn = None


def setup_rpc(node: ISSHHost, rpc_server_code: bytes, plugins: Dict[str, bytes] = None, port: int = 0) -> IRPCNode:
    log_file = node.run("mktemp").strip()
    code_file = node.put_to_file(None, rpc_server_code)
    ip = node.info.ssh_creds.addr.host

    cmd = "python {code_file} server --listen-addr={listen_ip}:{port} --daemon " + \
          "--show-settings --stdout-file={out_file}"
    cmd = cmd.format(code_file=code_file, listen_ip=ip, out_file=log_file, port=port)
    params_js = node.run(cmd).strip()
    params = json.loads(params_js)
    params['log_file'] = log_file
    node.info.params.update(params)

    port = int(params['addr'].split(":")[1])
    rpc_conn = agent.connect((ip, port))

    if plugins is not None:
        try:
            for name, code in plugins.items():
                rpc_conn.server.load_module(name, None, code)
        except Exception:
            rpc_conn.server.stop()
            rpc_conn.disconnect()
            raise

    return RPCNode(rpc_conn, node.info)



        # class RemoteNode(node_interfaces.IRPCNode):
#     def __init__(self, node_info: node_interfaces.NodeInfo, rpc_conn: agent.RPCClient):
#         self.info = node_info
#         self.rpc = rpc_conn
#
    # def get_interface(self, ip: str) -> str:
    #     """Get node external interface for given IP"""
    #     data = self.run("ip a", nolog=True)
    #     curr_iface = None
    #
    #     for line in data.split("\n"):
    #         match1 = re.match(r"\d+:\s+(?P<name>.*?):\s\<", line)
    #         if match1 is not None:
    #             curr_iface = match1.group('name')
    #
    #         match2 = re.match(r"\s+inet\s+(?P<ip>[0-9.]+)/", line)
    #         if match2 is not None:
    #             if match2.group('ip') == ip:
    #                 assert curr_iface is not None
    #                 return curr_iface
    #
    #     raise KeyError("Can't found interface for ip {0}".format(ip))
    #
    # def get_user(self) -> str:
    #     """"get ssh connection username"""
    #     if self.ssh_conn_url == 'local':
    #         return getpass.getuser()
    #     return self.ssh_cred.user
    #
    #
    # def run(self, cmd: str, stdin_data: str = None, timeout: int = 60, nolog: bool = False) -> Tuple[int, str]:
    #     """Run command on node. Will use rpc connection, if available"""
    #
    #     if self.rpc_conn is None:
    #         return run_over_ssh(self.ssh_conn, cmd,
    #                             stdin_data=stdin_data, timeout=timeout,
    #                             nolog=nolog, node=self)
    #     assert not stdin_data
    #     proc_id = self.rpc_conn.cli.spawn(cmd)
    #     exit_code = None
    #     output = ""
    #
    #     while exit_code is None:
    #         exit_code, stdout_data, stderr_data = self.rpc_conn.cli.get_updates(proc_id)
    #         output += stdout_data + stderr_data
    #
    #     return exit_code, output


