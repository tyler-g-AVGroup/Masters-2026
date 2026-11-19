using System;
using Crestron.SimplSharp;
using Crestron.SimplSharpPro;
using Crestron.SimplSharpPro.CrestronThread;
using Crestron.SimplSharpPro.UI;
using Masters2026.Xpanel;

namespace Masters2026
{
    /// <summary>
    /// The control system the program will run on.
    /// </summary>
    public class ControlSystem : CrestronControlSystem
    {
        /// <summary>
        /// The panel to be used with the contracts.
        /// </summary>
        private XpanelForHtml5 xpanel;

        /// <summary>
        /// Initializes a new instance of the <see cref="ControlSystem"/> class.
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
        /// You cannot send / receive data in the constructor.
        /// </summary>
        public ControlSystem()
            : base()
        {
            try
            {
                Thread.MaxNumberOfUserThreads = 20;

                // Subscribe to the controller events (System, Program, and Ethernet)
                CrestronEnvironment.SystemEventHandler += new SystemEventHandler(this.HandleControllerSystemEventHandler);
                CrestronEnvironment.ProgramStatusEventHandler += new ProgramStatusEventHandler(this.HandleControllerProgramEventHandler);
                CrestronEnvironment.EthernetEventHandler += new EthernetEventHandler(this.HandleControllerEthernetEventHandler);
            }
            catch (Exception e)
            {
                ErrorLog.Error("Error in the constructor: {0}", e.Message);
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
                this.xpanel = new XpanelForHtml5(3, this);
                this.xpanel.Register();

                new DemoPanel(this.xpanel);
            }
            catch (Exception e)
            {
                ErrorLog.Error("Error in InitializeSystem: {0}", e.Message);
            }
        }

        /// <summary>
        /// Event Handler for Ethernet events: Link Up and Link Down.
        /// Use these events to close / re-open sockets, etc.
        /// </summary>
        /// <param name="ethernetEventArgs">This parameter holds the values
        /// such as whether it's a Link Up or Link Down event. It will also indicate
        /// which Ethernet adapter this event belongs to.
        /// </param>
        private void HandleControllerEthernetEventHandler(EthernetEventArgs ethernetEventArgs)
        {
            switch (ethernetEventArgs.EthernetEventType)
            {
                case eEthernetEventType.LinkDown:
                    if (ethernetEventArgs.EthernetAdapter == EthernetAdapterType.EthernetLANAdapter)
                    {
                    }

                    break;
                case eEthernetEventType.LinkUp:
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
        /// for other programs stopping.
        /// </summary>
        /// <param name="programStatusEventType">The <see cref="eProgramStatusEventType"/>.</param>
        private void HandleControllerProgramEventHandler(eProgramStatusEventType programStatusEventType)
        {
            switch (programStatusEventType)
            {
                case eProgramStatusEventType.Paused:

                    // The program has been paused.  Pause all user threads/timers as needed.
                    break;
                case eProgramStatusEventType.Resumed:

                    // The program has been resumed. Resume all the user threads/timers as needed.
                    break;
                case eProgramStatusEventType.Stopping:

                    // The program has been stopped.
                    // Close all threads.
                    // Shutdown all Client/Servers in the system.
                    // General cleanup.
                    // Unsubscribe to all System Monitor events.
                    break;
            }
        }

        /// <summary>
        /// Event Handler for system events, Disk Inserted/Ejected, and Reboot
        /// Use this event to clean up when someone types in reboot, or when your SD /USB
        /// removable media is ejected / re-inserted.
        /// </summary>
        /// <param name="systemEventType">A <see cref="eSystemEventType"/>.</param>
        private void HandleControllerSystemEventHandler(eSystemEventType systemEventType)
        {
            switch (systemEventType)
            {
                case eSystemEventType.DiskInserted:

                    // Removable media was detected on the system
                    break;
                case eSystemEventType.DiskRemoved:

                    // Removable media was detached from the system
                    break;
                case eSystemEventType.Rebooting:

                    // The system is rebooting.
                    // Very limited time to preform clean up and save any settings to disk.
                    break;
            }
        }
    }
}