using CMCPP502;

namespace Masters2026.Xpanel
{
    /// <summary>
    /// Implements the Crestron Construct contracts for the page 5 controls.
    /// </summary>
    internal class Page05KeypadPad
    {
        /// <summary>
        /// The contracts to be implemented within the page.
        /// </summary>
        private readonly Contract contract;

        /// <summary>
        /// Initializes a new instance of the <see cref="Page05KeypadPad"/> class.
        /// </summary>
        /// <param name="contract">The contracts to implement with this control page.</param>
        internal Page05KeypadPad(Contract contract)
        {
            this.contract = contract;
            this.contract.Page05.Keypad.Button_PressEvent += this.HandleKeypadButtonPressEvent;
        }

        /// <summary>
        /// Event handler for when a button on the keypad is pressed.
        /// </summary>
        /// <param name="sender">Where the event originated.</param>
        /// <param name="e">A <see cref="KeypadEventArgs"/>.</param>
        private void HandleKeypadButtonPressEvent(object sender, KeypadEventArgs e)
        {
            EventViewer.AddEventToViewer("KeypadButton", e);

            this.contract.Page05.KeypadFeedback_Indirect(string.Format("{0} {1}", e.KeypadButton.ToString(), e.SigArgs.Sig.BoolValue ? "Pressed" : "Released"));

            ////switch (e.KeypadButton)
            ////{
            ////    case KeypadButton.Button_0:
            ////        {
            ////            if (e.SigArgs.Sig.BoolValue)
            ////            {
            ////                this.contract.Page05.KeypadFeedback_Indirect("Keypad 0 Pressed");
            ////            }
            ////            else
            ////            {
            ////                this.contract.Page05.KeypadFeedback_Indirect("Keypad 0 Released");
            ////            }

            ////            break;
            ////        }

            ////    case KeypadButton.Button_1:
            ////        {
            ////            if (e.SigArgs.Sig.BoolValue)
            ////            {
            ////                this.contract.Page05.KeypadFeedback_Indirect("Keypad 1 Pressed");
            ////            }
            ////            else
            ////            {
            ////                this.contract.Page05.KeypadFeedback_Indirect("Keypad 1 Released");
            ////            }

            ////            break;
            ////        }
            ////}
        }
    }
}
