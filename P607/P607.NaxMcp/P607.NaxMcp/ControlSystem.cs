using System;
using Crestron.SimplSharp;                          	// For Basic SIMPL# Classes
using Crestron.SimplSharp.CrestronIO;                   // For Directory / File / Path
using Crestron.SimplSharpPro;                       	// For Basic SIMPL#Pro classes
using Crestron.SimplSharpPro.CrestronThread;        	// For Threading
using Crestron.SimplSharp.Python;         	            // For Python Module Support

namespace P607.NaxMcp
{
    public class ControlSystem : CrestronControlSystem
    {
        #region Constants
        const string ServerPort = "8766";

        #endregion

        #region Properties
        /// <summary>
        /// The python module instance running the MCP server demonstratation
        /// </summary>
        private readonly PythonModuleInstance demoMcpServer;
        #endregion

        #region Constructor
        /// <summary>
        /// ControlSystem Constructor. Starting point for the SIMPL#Pro program.
        /// Use the constructor to:
        /// * Initialize the maximum number of threads (max = 400)
        /// * Register devices
        /// * Register event handlers
        /// * Add Console Commands
        /// 
        /// Please be aware that the constructor needs to exit quickly; if it doesn't
        /// exit in time, the SIMPL#Pro program will exit.
        /// 
        /// You cannot send / receive data in the constructor
        /// </summary>
        public ControlSystem()
            : base()
        {
            try
            {
                Thread.MaxNumberOfUserThreads = 20;

                // The config.json file is expected to be in the User directory of the application root.
                var configPath = Path.Combine(Directory.GetApplicationRootDirectory(), "User/config.json");
                
                ErrorLog.Notice($"[P607] config path: {configPath} (exists: {File.Exists(configPath)})");

                // Check if the config.json file exists. If it doesn't, throw a FileNotFoundException.
                if (!File.Exists(configPath))
                {
                    // This is pretty terminal so throw an exception.
                    throw new FileNotFoundException($"config.json not found at {configPath}");
                }

                // Run the Python server script.
                demoMcpServer = SimplSharpPythonInterface.Run("demoMcpServer", "python/server.py", DemoServerCallback, new string[] { ServerPort, configPath, "0.0.0.0" });
               
                //Subscribe to the controller events (System, Program, and Ethernet)
                CrestronEnvironment.SystemEventHandler += new SystemEventHandler(_ControllerSystemEventHandler);
                CrestronEnvironment.ProgramStatusEventHandler += new ProgramStatusEventHandler(_ControllerProgramEventHandler);
                CrestronEnvironment.EthernetEventHandler += new EthernetEventHandler(_ControllerEthernetEventHandler);
            }
            catch (Exception e)
            {
                ErrorLog.Error($"Error in the constructor: {e.Message}");
            }
        }

        /// <summary>
        /// InitializeSystem - this method gets called after the constructor 
        /// has finished. 
        /// 
        /// Use InitializeSystem to:
        /// * Start threads
        /// * Configure ports, such as serial and verisports
        /// * Start and initialize socket connections
        /// Send initial device configurations
        /// 
        /// Please be aware that InitializeSystem needs to exit quickly also; 
        /// if it doesn't exit in time, the SIMPL#Pro program will exit.
        /// </summary>
        public override void InitializeSystem()
        {
            try
            {

            }
            catch (Exception e)
            {
                ErrorLog.Error($"Error in InitializeSystem: {e.Message}");
            }
        }
        #endregion

        #region Python Event Handlers
        // Every Python message lands here. {"debug": "..."} logs just the text; anything else is logged raw.
        private void DemoServerCallback(object sender, PythonDataReceivedEventArgs e)
        {
            string text = e.Data;
            try
            {
                text = Newtonsoft.Json.Linq.JObject.Parse(e.Data)["debug"]?.ToString() ?? e.Data;
            }
            catch (Exception)
            {
                // not JSON: log as received
            }
            // Log the message to the Crestron log.
            // Use journalctl -u virtualcontrol -f -all in the Alma Linux console to see the logs in real time.
            ErrorLog.Notice($"[python] {text}");
        }
        #endregion

        #region System Event Handlers
        /// <summary>
        /// Event Handler for Ethernet events: Link Up and Link Down. 
        /// Use these events to close / re-open sockets, etc. 
        /// </summary>
        /// <param name="ethernetEventArgs">This parameter holds the values 
        /// such as whether it's a Link Up or Link Down event. It will also indicate 
        /// wich Ethernet adapter this event belongs to.
        /// </param>
        void _ControllerEthernetEventHandler(EthernetEventArgs ethernetEventArgs)
        {
            switch (ethernetEventArgs.EthernetEventType)
            {//Determine the event type Link Up or Link Down
                case (eEthernetEventType.LinkDown):
                    //Next need to determine which adapter the event is for. 
                    //LAN is the adapter is the port connected to external networks.
                    if (ethernetEventArgs.EthernetAdapter == EthernetAdapterType.EthernetLANAdapter)
                    {
                        //
                    }
                    break;
                case (eEthernetEventType.LinkUp):
                    if (ethernetEventArgs.EthernetAdapter == EthernetAdapterType.EthernetLANAdapter)
                    {

                    }
                    break;
            }
        }

        /// <summary>
        /// Event Handler for Programmatic events: Stop, Pause, Resume.
        /// Use this event to clean up when a program is stopping, pausing, and resuming.
        /// This event only applies to this SIMPL#Pro program, it doesn't receive events
        /// for other programs stopping
        /// </summary>
        /// <param name="programStatusEventType"></param>
        void _ControllerProgramEventHandler(eProgramStatusEventType programStatusEventType)
        {
            switch (programStatusEventType)
            {
                case (eProgramStatusEventType.Paused):
                    //The program has been paused.  Pause all user threads/timers as needed.
                    break;
                case (eProgramStatusEventType.Resumed):
                    //The program has been resumed. Resume all the user threads/timers as needed.
                    break;
                case (eProgramStatusEventType.Stopping):
                    demoMcpServer?.SendData("{\"Running\": \"False\"}");

                    //The program has been stopped.
                    //Close all threads. 
                    //Shutdown all Client/Servers in the system.
                    //General cleanup.
                    //Unsubscribe to all System Monitor events
                    break;
            }

        }

        /// <summary>
        /// Event Handler for system events, Disk Inserted/Ejected, and Reboot
        /// Use this event to clean up when someone types in reboot, or when your SD /USB
        /// removable media is ejected / re-inserted.
        /// </summary>
        /// <param name="systemEventType"></param>
        void _ControllerSystemEventHandler(eSystemEventType systemEventType)
        {
            switch (systemEventType)
            {
                case (eSystemEventType.DiskInserted):
                    //Removable media was detected on the system
                    break;
                case (eSystemEventType.DiskRemoved):
                    //Removable media was detached from the system
                    break;
                case (eSystemEventType.Rebooting):
                    //The system is rebooting. 
                    //Very limited time to preform clean up and save any settings to disk.
                    break;
            }

        }
        #endregion
    }
}