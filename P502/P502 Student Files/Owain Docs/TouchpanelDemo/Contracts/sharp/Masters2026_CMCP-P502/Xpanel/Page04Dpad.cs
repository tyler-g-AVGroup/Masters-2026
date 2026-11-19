using CMCPP502;

namespace Masters2026.Xpanel
{
    /// <summary>
    /// Implements the Crestron Construct contracts for the page 4 controls.
    /// </summary>
    internal class Page04Dpad
    {
        /// <summary>
        /// The contracts to be implemented within the page.
        /// </summary>
        private readonly Contract contract;

        /// <summary>
        /// Initializes a new instance of the <see cref="Page04Dpad"/> class.
        /// </summary>
        /// <param name="contract">The contracts to implement with this control page.</param>
        internal Page04Dpad(Contract contract)
        {
            this.contract = contract;
            this.contract.Page04.Dpad.Button_PressEvent += this.HandleDpadButtonPressEvent;
        }

        /// <summary>
        /// Event handler for when a button on the directional pad is pressed.
        /// </summary>
        /// <param name="sender">Where the event originated.</param>
        /// <param name="e">A <see cref="DpadEventArgs"/>.</param>
        private void HandleDpadButtonPressEvent(object sender, DpadEventArgs e)
        {
            EventViewer.AddEventToViewer("DPadButton", e);

            switch (e.DpadButton)
            {
                case DpadButton.Up:
                    if (e.SigArgs.Sig.BoolValue)
                    {
                        this.contract.Page04.DPadFeedback_Indirect("Up Press");
                    }
                    else
                    {
                        this.contract.Page04.DPadFeedback_Indirect("Up Release");
                    }

                    break;

                case DpadButton.Down:
                    if (e.SigArgs.Sig.BoolValue)
                    {
                        this.contract.Page04.DPadFeedback_Indirect("Down Press");
                    }
                    else
                    {
                        this.contract.Page04.DPadFeedback_Indirect("Down Release");
                    }

                    break;

                case DpadButton.Left:
                    if (e.SigArgs.Sig.BoolValue)
                    {
                        this.contract.Page04.DPadFeedback_Indirect("Left Press");
                    }
                    else
                    {
                        this.contract.Page04.DPadFeedback_Indirect("Left Release");
                    }

                    break;

                case DpadButton.Right:
                    if (e.SigArgs.Sig.BoolValue)
                    {
                        this.contract.Page04.DPadFeedback_Indirect("Right Press");
                    }
                    else
                    {
                        this.contract.Page04.DPadFeedback_Indirect("Right Release");
                    }

                    break;

                case DpadButton.Center:
                    if (e.SigArgs.Sig.BoolValue)
                    {
                        this.contract.Page04.DPadFeedback_Indirect("Center Press");
                    }
                    else
                    {
                        this.contract.Page04.DPadFeedback_Indirect("Center Release");
                    }

                    break;
            }
        }
    }
}
