// CATS 外部 API 探测：CATSBizManager.CatsConnect + CatsLogin + SubMarketData
// 编译（在 CATS 安装目录下）:
//   csc /platform:x64 /r:CATSAPI_CSharp.dll /r:CATSBizManager_CSharp.dll /out:cats_biz_md.exe <本文件>
// 运行:
//   set CATS_USER=你的账号
//   set CATS_PASSWORD=你的密码
//   set CATS_OUT=D:\cursor_space\lahm\data\cats
//   cats_biz_md.exe
//
// 当前实测：TCP/TASP 握手可成功，但网关登录返回
//   illegal user or incorrect password
// 需确认 GUI 登录框里的“服务器名称(serverName)”以及账号是否被锁定。

using System;
using System.IO;
using System.Text;
using System.Threading;
using CATSBizManager_CSharp;

public class CatsBizMd
{
    static AutoResetEvent connectDone = new AutoResetEvent(false);
    static AutoResetEvent loginDone = new AutoResetEvent(false);
    static int mdCount = 0;
    static StringBuilder mdLog = new StringBuilder();
    static int lastCode = -999;
    static string lastErr = "";

    static void OnConnect(CRetVal<CATSBizCatsClientUpdateInfo> rv)
    {
        lastCode = rv.nRetCode;
        lastErr = rv.sErrorMsg ?? "";
        Console.WriteLine("ConnectCB " + lastCode + " " + lastErr);
        connectDone.Set();
    }

    static void OnLogin(CRetVal<CATSBizCatsAcctInfo> rv)
    {
        lastCode = rv.nRetCode;
        lastErr = rv.sErrorMsg ?? "";
        Console.WriteLine("LoginCB " + lastCode + " " + lastErr);
        loginDone.Set();
    }

    static void OnMd(CATSBizMarketData md)
    {
        if (md == null) return;
        string line = string.Format(
            "MD symbol={0} last={1} open={2} high={3} low={4} prevClose={5} vol={6} turnover={7} time={8}",
            md.m_strSymbol, md.m_dblLastPrice, md.m_dblOpenPrice, md.m_dblHighPrice,
            md.m_dblLowPrice, md.m_dblPrevClosePrice, md.m_nVolume, md.m_dblTurnover, md.m_strTime);
        Console.WriteLine(line);
        lock (mdLog) { mdLog.AppendLine(line); mdCount++; }
    }

    static void OnMdAns(CRetVal<int> rv)
    {
        Console.WriteLine("MdAns " + rv.nRetCode + " " + rv.sErrorMsg);
    }

    public static int Main(string[] args)
    {
        string root = Path.GetDirectoryName(System.Reflection.Assembly.GetExecutingAssembly().Location);
        Directory.SetCurrentDirectory(root);
        string user = Environment.GetEnvironmentVariable("CATS_USER") ?? "";
        string pwd = Environment.GetEnvironmentVariable("CATS_PASSWORD") ?? "";
        string sn = Environment.GetEnvironmentVariable("CATS_SERVERNAME") ?? "acct_ip_debug";
        string outDir = Environment.GetEnvironmentVariable("CATS_OUT") ?? @"D:\cursor_space\lahm\data\cats";
        Directory.CreateDirectory(outDir);
        if (user.Length == 0 || pwd.Length == 0)
        {
            Console.WriteLine("Set CATS_USER / CATS_PASSWORD");
            return 10;
        }

        TS_Notify_t idle = new TS_Notify_t(delegate(long a) { });
        CATSBizManager mgr = CATSBizManager.GetInstance();
        Console.WriteLine("Init " + mgr.Init(0, idle, 0, idle, 0, idle, 0, idle, 0));
        CCatsAcctManager am = mgr.GetCatsAcctManager();

        CatsConnectReqField req = new CatsConnectReqField();
        req.catsClient = "WCATSWPF";
        req.srcIpAddr = "192.168.0.100";
        req.srcPhyAddr = "BC6EE222ECE0|005056C00001";
        req.serverName = sn;
        req.user = user;
        req.password = pwd;
        req.tradingServerAddr = "123.88.147.88";
        req.tradingServerPort = "12000";
        req.hqServerAddr = "123.88.147.88";
        req.hqServerPort = "11000";

        connectDone.Reset();
        try
        {
            Console.WriteLine("CatsConnect id=" + am.CatsConnect(req, new T_CatsBizNotify<CATSBizCatsClientUpdateInfo>(OnConnect), 0));
        }
        catch (CATSBizException ex)
        {
            Console.WriteLine("ConnectThrow " + ex.ErrorCode + " " + ex.ErrorMsg);
        }
        bool sig = connectDone.WaitOne(30000);
        Console.WriteLine("ConnectWait sig=" + sig + " code=" + lastCode + " err=" + lastErr);
        if (!(sig && lastCode == 0)) return 3;

        CatsLoginReqField login = new CatsLoginReqField();
        login.catsAcct = user;
        login.catsPassword = pwd;
        login.identityString = "";
        login.wealthCatsVersion = "4.1.2025.33";
        loginDone.Reset();
        lastCode = -999;
        try
        {
            Console.WriteLine("CatsLogin id=" + am.CatsLogin(login, new T_CatsBizNotify<CATSBizCatsAcctInfo>(OnLogin), 0));
        }
        catch (CATSBizException ex)
        {
            Console.WriteLine("LoginThrow " + ex.ErrorCode + " " + ex.ErrorMsg);
        }
        sig = loginDone.WaitOne(30000);
        Console.WriteLine("LoginWait sig=" + sig + " code=" + lastCode + " err=" + lastErr);
        if (sig && lastCode == 0) mgr.CATSLogined(true);

        CCatsMDManager md = mgr.GetCatsMDManager();
        T_CatsPubNotify<CATSBizMarketData> pub = new T_CatsPubNotify<CATSBizMarketData>(OnMd);
        T_CatsBizNotify<int> ans = new T_CatsBizNotify<int>(OnMdAns);
        foreach (string sym in new string[] { "600030.SH", "000001.SZ" })
        {
            Console.WriteLine("sub " + sym);
            md.SubMarketData(sym, pub, ans, 0);
            DateTime until = DateTime.Now.AddSeconds(10);
            while (DateTime.Now < until)
            {
                Thread.Sleep(400);
                CATSBizMarketData g = md.GetMarketData(sym);
                if (g != null && g.m_dblLastPrice > 0) OnMd(g);
                lock (mdLog) { if (mdCount >= 4) break; }
            }
        }

        string path = Path.Combine(outDir, "md_sample_" + DateTime.Now.ToString("yyyyMMdd_HHmmss") + ".txt");
        lock (mdLog)
        {
            File.WriteAllText(path, "serverName=" + sn + " user=" + user + " mdCount=" + mdCount + "\r\n" + mdLog.ToString(), Encoding.UTF8);
        }
        Console.WriteLine("WROTE " + path + " mdCount=" + mdCount);
        return mdCount > 0 ? 0 : 4;
    }
}
