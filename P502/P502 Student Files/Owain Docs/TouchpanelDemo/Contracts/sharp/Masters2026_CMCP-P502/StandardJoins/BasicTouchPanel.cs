using System;
using System.Globalization;
using Crestron.SimplSharp;
using Crestron.SimplSharp.CrestronIO;
using Crestron.SimplSharpPro;
using Crestron.SimplSharpPro.DeviceSupport;
using Crestron.SimplSharpPro.UI;

namespace Masters2026.StandardJoins
{
    /// <summary>
    /// Provides a basic example of how to implement a touch panel using standard join numbers.
    /// </summary>
    public class BasicTouchPanel
    {
        /// <summary>
        /// Backing field for the touch panel we are going to register.
        /// </summary>
        private readonly BasicTriListWithSmartObject panel;

        /// <summary>
        /// Initializes a new instance of the <see cref="BasicTouchPanel"/> class.
        /// Instantiates a touch panel. Registers the panel and subscribes to join/smart graphic events.
        /// </summary>
        /// <param name="controlSystem">The control system the panel should be registered to.</param>
        /// <param name="ipid">The IPID used for communication.</param>
        public BasicTouchPanel(ControlSystem controlSystem, uint ipid)
        {
            try
            {
                // Instantiates a new instance of a TSW panel. It is assigned to a field of type "BasicTriListWithSmartObject" because that is the base object which can be used for many panel types. This way you can create logic which is agnostic
                // to the actual model used.
                this.panel = new Tsw1060(ipid, controlSystem);

                // Loads the SGD which allows you to interact with the smart objects.
                this.panel.LoadSmartObjects($"{Directory.GetApplicationDirectory()}/PanelName.sgd");

                // Registers the panel with the control system.
                this.panel.Register();

                // Subscribes to the event for when non-smart graphic buttons/sliders/textboxes are interacted with.
                this.panel.SigChange += this.HandlePanelSigChange;

                // Subscribes to the event for when smart graphic ID 2 is interacted with.
                this.panel.SmartObjects[2].SigChange += this.HandleSmartObjectPanelSigChange;
            }
            catch (Exception ex)
            {
                ErrorLog.Error($"Error in BasicTouchPanel constructor: {ex}");
            }
        }

        /// <summary>
        /// Event handler for when non-smart graphic buttons/sliders/textboxes are interacted with.
        /// </summary>
        /// <param name="currentDevice">The device which raised the event.</param>
        /// <param name="signalEvent">Contains information about the object which has changed.</param>
        private void HandlePanelSigChange(BasicTriList currentDevice, SigEventArgs signalEvent)
        {
            ErrorLog.Notice($"SignalChangeHandler: {signalEvent.Event} | {signalEvent.Sig.Name} | {signalEvent.Sig.Number}");

            // Determines what type of control has changed: Bool (Digital), UShort (Analog), String (Serial)
            switch (signalEvent.Event)
            {
                // Was it a Bool/Digital change
                case eSigEvent.BoolChange:

                    // Determine the join number associated with the event
                    switch (signalEvent.Sig.Number)
                    {
                        // Was it join number 100
                        case 100:
                            // Was the button pressed (true) or release (false)
                            if (signalEvent.Sig.BoolValue)
                            {
                                // Set the feedback for button 10 to true/high.
                                this.panel.BooleanInput[10].BoolValue = true;
                            }
                            else
                            {
                                // Do something when the button is released.
                            }

                            break;

                        // Was it join number 101
                        case 101:
                            if (signalEvent.Sig.BoolValue)
                            {
                                // Do something when button 101 is pressed.
                            }

                            break;
                    }

                    break;

                // Was it a UShort/Analog change
                case eSigEvent.UShortChange:
                    {
                        // Determine the join number associated with the event
                        switch (signalEvent.Sig.Number)
                        {
                            // Was it join number 100
                            case 100:
                                {
                                    // Sets the feedback for Ushort/Analog join 10 to max.
                                    this.panel.UShortInput[10].UShortValue = 65535;
                                    break;
                                }

                            // Was it join number 101
                            case 101:
                                {
                                    // Do something when Ushort/Analog join 101 has changed.
                                    break;
                                }
                        }
                    }

                    break;

                // Was it a String/Serial change
                case eSigEvent.StringChange:
                    {
                        // Determine the join number associated with the event
                        switch (signalEvent.Sig.Number)
                        {
                            // Was it join number 100
                            case 100:
                                {
                                    // Sets the feedback for String/Serial join 10.
                                    this.panel.StringInput[10].StringValue = "Setting Feedback";
                                    break;
                                }

                            case 101:
                                {
                                    // Do something when String/Serial join 101 has changed.
                                break;
                                }
                        }
                    }

                    break;
            }
        }

        /// <summary>
        /// Event handler for when smart graphic buttons/sliders/textboxes are interacted with.
        /// </summary>
        /// <param name="currentDevice">The device which raised the event.</param>
        /// <param name="smartSignalEvent">Contains information about the object which has changed.</param>
        private void HandleSmartObjectPanelSigChange(GenericBase currentDevice, SmartObjectEventArgs smartSignalEvent)
        {
            // Determines what type of control has changed: Bool (Digital), UShort (Analog), String (Serial)
            switch (smartSignalEvent.Event)
            {
                // Was it a Bool/Digital change
                case eSigEvent.BoolChange:
                    // What is the name of the button associated with the Bool/Digital event. You can also use join numbers here; however, different smart object types have different offsets.
                    // The names can be found by looking at the smart object extender in Simpl Windows. You will see the names on the button lists.
                    switch (smartSignalEvent.Sig.Name)
                    {
                        case "press1":
                            if (smartSignalEvent.Sig.BoolValue)
                            {
                                // Sets the feedback for smart object 2, button 1 to true/high.
                                this.panel.SmartObjects[2].BooleanInput["Item 1 Enable"].BoolValue = true;
                            }

                            break;
                    }

                    break;
            }
        }

        private void PopulateSubpageReferenceListExample(object sender, EventArgs e)
        {
            ushort count = 50;
            uint index = 1;
            uint index2 = 2;

            this.panel.SmartObjects[18].UShortInput["Set Number of Items"].UShortValue = count;

            for (var i = 0; i < count; i++)
            {
                this.panel.SmartObjects[18].StringInput[string.Format("text-o{0}", index)].StringValue = "Example String";
                this.panel.SmartObjects[18].BooleanInput[string.Format("fb{0}", index2)].BoolValue = true;
                index += 2;
                index2 += 2;
            }
        }

        //private void NastySrlExample(object sender, ParticipantUpdatedEventArgs e)
        //{
        //    const uint SerialOffset = 3;
        //    const uint SerialDisplayNameJoin = 1;
        //    const uint SerialDetailsJoin = 2;
        //    const uint SerialExtendedInfoJoin = 3;

        //    const uint DigitalOffset = 3;
        //    const uint DigitalMuteJoin = 2;
        //    const uint DigitalIsHandRaisedJoin = 3;

        //    if (e.UpdateType != ListUpdateTypes.ItemUpdated)
        //    {
        //        var count = (ushort)Math.Min(50, 5);
        //        this.ui.UShortInput[150].UShortValue = 5;
        //        this.ui.SmartObjects[7].UShortInput["Set Number of Items"].UShortValue = count;
        //    }

        //    if (e.UpdateType == ListUpdateTypes.ItemAdded || e.UpdateType == ListUpdateTypes.ItemUpdated)
        //    {
        //        this.ui.SmartObjects[7].StringInput[string.Format("text-o{0}", (e.Index * SerialOffset) + SerialDisplayNameJoin)].StringValue = "string";
        //        this.ui.SmartObjects[7].StringInput[string.Format("text-o{0}", (e.Index * SerialOffset) + SerialDetailsJoin)].StringValue = "string";
        //        this.ui.SmartObjects[7].StringInput[string.Format("text-o{0}", (e.Index * SerialOffset) + SerialExtendedInfoJoin)].StringValue = "string";
        //        this.ui.SmartObjects[7].BooleanInput[string.Format("fb{0}", (e.Index * DigitalOffset) + DigitalMuteJoin)].BoolValue = true;
        //        this.ui.SmartObjects[7].BooleanInput[string.Format("fb{0}", (e.Index * DigitalOffset) + DigitalIsHandRaisedJoin)].BoolValue = true;

        //        if (e.UpdateType == ListUpdateTypes.ItemUpdated && e.Index == this.selectedParticipantIndex)
        //        {
        //            this.UpdateSelectedParticipant();
        //        }
        //    }
        //    else if (e.UpdateType == ListUpdateTypes.RefreshAll)
        //    {
        //        for (var i = 0; i < 5; i++)
        //        {
        //            this.ui.SmartObjects[7].StringInput[string.Format("text-o{0}", (i * SerialOffset) + SerialDisplayNameJoin)].StringValue = "string";
        //            this.ui.SmartObjects[7].StringInput[string.Format("text-o{0}", (i * SerialOffset) + SerialDetailsJoin)].StringValue = "string";
        //            this.ui.SmartObjects[7].StringInput[string.Format("text-o{0}", (i * SerialOffset) + SerialExtendedInfoJoin)].StringValue = "string";
        //            this.ui.SmartObjects[7].BooleanInput[string.Format("fb{0}", (i * DigitalOffset) + DigitalMuteJoin)].BoolValue = true;
        //            this.ui.SmartObjects[7].BooleanInput[string.Format("fb{0}", (i * DigitalOffset) + DigitalIsHandRaisedJoin)].BoolValue = true;
        //        }
        //    }
        //}
    }
}
