using System;
using System.Threading.Tasks;
using Crestron.SimplSharp;
using Crestron.SimplSharpPro;
using Crestron.SimplSharpPro.DeviceSupport;
using Crestron.SimplSharpPro.UI;
using Masters2026.StandardJoins.PanelUtilities;

namespace Masters2026.StandardJoins
{
    /// <summary>
    /// Provides a advanced example of how to implement a touch panel using standard join numbers where the user object is used to invoke methods.
    /// </summary>
    public class AdvancedTouchPanel
    {
        /// <summary>
        /// Backing field for the touch panel we are going to register.
        /// </summary>
        private readonly BasicTriListWithSmartObject panel;

        /// <summary>
        /// Initializes a new instance of the <see cref="AdvancedTouchPanel"/> class.
        /// Instantiates a touch panel. Registers the panel and subscribes to join/smart graphic events.
        /// </summary>
        /// <param name="controlSystem">The control system the panel should be registered to.</param>
        /// <param name="ipid">The IPID used for communication.</param>
        /// <param name="hardware">The name of the hardware class to use for the panel.</param>
        public AdvancedTouchPanel(ControlSystem controlSystem, uint ipid, string hardware)
        {
            switch (hardware)
            {
                case "tsw1060":
                    {
                        this.panel = new Tsw1060(ipid, controlSystem);
                        break;
                    }
            }

            this.panel.LoadSmartObjects($"{Crestron.SimplSharp.CrestronIO.Directory.GetApplicationDirectory()}/PanelName.sgd");
            this.panel.SigChange += this.HandlePanelSigChange;

            foreach (var smartObject in this.panel.SmartObjects.Values)
            {
                smartObject.SigChange += this.HandleSmartObjectSigChange;
            }

            this.panel.Register();

            this.panel.AddBooleanAction(100, (buttonState) =>
            {
                if (buttonState)
                {
                    // Do something when non smart graphics bool/digital join 100 is pressed.
                }
                else
                {
                    // Do something when non smart graphics bool/digital join 100 is released.
                }
            });

            this.panel.AddBooleanAction(2, "press1", (buttonState) =>
            {
                // Do something when smart object ID 2, button one state changes.
            });
        }

        /// <summary>
        /// Handles the events associated with smart graphics.
        /// </summary>
        /// <param name="currentDevice">The device which invoked the event.</param>
        /// <param name="smartSignalEvent">Contains the detail of the smart graphic changes.</param>
        private void HandleSmartObjectSigChange(GenericBase currentDevice, SmartObjectEventArgs smartSignalEvent)
        {
            if (smartSignalEvent.Sig.UserObject is Action<bool> boolAction)
            {
                this.SafeInvokeDelegates(boolAction, smartSignalEvent.Sig.BoolValue, smartSignalEvent);
            }
        }

        /// <summary>
        /// Handles the events associated with basic joins.
        /// </summary>
        /// <param name="currentDevice">The device which invoked the event.</param>
        /// <param name="signalEvent">Contains the detail of the join which changed.</param>
        private void HandlePanelSigChange(BasicTriList currentDevice, SigEventArgs signalEvent)
        {
            if (signalEvent.Sig.UserObject is Action<bool> boolAction)
            {
                this.SafeInvokeDelegates(boolAction, signalEvent.Sig.BoolValue, signalEvent);
            }
        }

        /// <summary>
        /// Invoke the delegates within a try catch so that errors can be caught, while also using Tasks so that UI interactions are not blocked.
        /// </summary>
        /// <typeparam name="T">The type of join to associate the action with.</typeparam>
        /// <param name="actions">The action to be invoked.</param>
        /// <param name="param">The parameters to invoke the action with.</param>
        /// <param name="e">The event args from the signal change event.</param>
        private void SafeInvokeDelegates<T>(Action<T> actions, T param, SigEventArgs e)
        {
            foreach (var del in actions.GetInvocationList())
            {
                if (del is Action<T> action)
                {
                    try
                    {
                        Task.Run(() => action(param));
                    }
                    catch (Exception ex)
                    {
                        ErrorLog.Error($"Exception during {e.Event} on '{e.Sig.Name}'/ Join {e.Sig.Number} with value {param}");
                        ErrorLog.Error($"{ex}");
                    }
                }
            }
        }
    }
}
