using CMCPP502;
using Crestron.SimplSharp;

namespace Masters2026.Xpanel
{
    /// <summary>
    /// Implements the Crestron Construct contracts for the page 3 controls.
    /// </summary>
    internal class Page03Text
    {
        /// <summary>
        /// The contracts to be implemented within the page.
        /// </summary>
        private readonly Contract contract;

        /// <summary>
        /// Used to only update the text box input after a delay.
        /// </summary>
        private readonly CTimer textInputDebounceTimer;

        /// <summary>
        /// Hold the pending string value used to update the feedback on the text box input.
        /// </summary>
        private string pendingTextValue;

        /// <summary>
        /// Initializes a new instance of the <see cref="Page03Text"/> class.
        /// </summary>
        /// <param name="contract">The contracts to implement with this control page.</param>
        internal Page03Text(Contract contract)
        {
            this.contract = contract;
            this.contract.Page03.Textinput_OutputTextEvent += this.HandleTextInputOutputTextEvent;
            this.contract.Page03.PowerOn_PressEvent += this.HandlePowerOnPressEvent;
            this.contract.Page03.PowerOff_PressEvent += this.HandlePowerOffPressEvent;
            this.contract.Page03.Textinput_IndirectText("Initial Value");

            this.textInputDebounceTimer = new CTimer(this.OnTextInputTimerCallback, null, Timeout.Infinite);
        }

        /// <summary>
        /// Event handler for when the power off button is pressed.
        /// </summary>
        /// <param name="sender">Where the event originated.</param>
        /// <param name="e">A <see cref="UIEventArgs"/>.</param>
        private void HandlePowerOffPressEvent(object sender, UIEventArgs e)
        {
            EventViewer.AddEventToViewer("PowerOffButton", e);

            if (e.SigArgs.Sig.BoolValue)
            {
                this.contract.Page03.FormattedText_Indirect("Power Off");
            }
        }

        /// <summary>
        /// Event handler for when the power on button is pressed.
        /// </summary>
        /// <param name="sender">Where the event originated.</param>
        /// <param name="e">A <see cref="UIEventArgs"/>.</param>
        private void HandlePowerOnPressEvent(object sender, UIEventArgs e)
        {
            EventViewer.AddEventToViewer("PowerOnButton", e);

            if (e.SigArgs.Sig.BoolValue)
            {
                this.contract.Page03.FormattedText_Indirect("Power On");
            }
        }

        /// <summary>
        /// Event handler for the text input box.
        /// </summary>
        /// <param name="sender">Where the event originated.</param>
        /// <param name="e">A <see cref="UIEventArgs"/>.</param>
        private void HandleTextInputOutputTextEvent(object sender, UIEventArgs e)
        {
            EventViewer.AddEventToViewer("TextInput", e);

            this.pendingTextValue = e.SigArgs.Sig.StringValue;
            this.textInputDebounceTimer.Reset(1500);
        }

        /// <summary>
        /// Callback for when the <see cref="textInputDebounceTimer"/> expires.
        /// </summary>
        /// <param name="obj">Unused.</param>
        private void OnTextInputTimerCallback(object obj)
        {
            this.contract.Page03.Textinput_IndirectText(this.pendingTextValue);
            this.contract.Page03.FormattedText_Indirect(this.pendingTextValue);
        }
    }
}
