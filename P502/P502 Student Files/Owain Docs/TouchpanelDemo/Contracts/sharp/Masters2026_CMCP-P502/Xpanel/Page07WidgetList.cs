using System.Linq.Expressions;
using CMCPP502;

namespace Masters2026.Xpanel
{
    /// <summary>
    /// Implements the Crestron Construct contracts for the page 7 controls.
    /// </summary>
    internal class Page07WidgetList
    {
        internal const ushort NumberOfMicrophones = 10; // How many mics we have.

        /// <summary>
        /// The contracts to be implemented within the page.
        /// </summary>
        private readonly Contract contract;

        /// <summary>
        /// Emulates a microphone control.
        /// </summary>
        private MicrophoneEmulator[] microphoneEmulators;

        /// <summary>
        /// Initializes a new instance of the <see cref="Page07WidgetList"/> class.
        /// </summary>
        /// <param name="contract">The contracts to implement with this control page.</param>
        internal Page07WidgetList(Contract contract)
        {
            this.contract = contract;
            this.SetupMicrophoneEmulators(NumberOfMicrophones);
            this.contract.Page07.MicWidgetList.MicWidgetList_Set_Number_Of_Items(NumberOfMicrophones);

            for (ushort i = 0; i < NumberOfMicrophones; i++)
            {
                ushort capturedIndex = i;
                MicrophoneEmulator microphone = this.microphoneEmulators[capturedIndex];
                microphone.MicrophoneChanged += (s, e) =>
                {
                    this.contract.Page07.MicWidgetList.MicMute_Selected(capturedIndex, e.Mute);
                    this.contract.Page07.MicWidgetList.MicLevel_Enabled(capturedIndex, !e.Mute);
                    this.contract.Page07.MicWidgetList.MicLevel_LowerTouchfb(capturedIndex, e.Level);
                };

                this.contract.Page07.MicWidgetList.MicLabel_Indirect(i, microphone.Label);
                this.contract.Page07.MicWidgetList.MicMute_Selected(i, microphone.Mute);
                this.contract.Page07.MicWidgetList.MicLevel_Enabled(i, !microphone.Mute);
                this.contract.Page07.MicWidgetList.MicLevel_LowerTouchfb(i, microphone.Level);
            }

            this.contract.Page07.MicWidgetList.MicMute_PressEvent += (s, e) =>
            {
                EventViewer.AddEventToViewer("MicMute", e);

                if (e.SigArgs.Sig.BoolValue)
                {
                    this.microphoneEmulators[e.WidgetItemIndex].Mute = !this.microphoneEmulators[e.WidgetItemIndex].Mute;
                }
            };
            this.contract.Page07.MicWidgetList.MicLevel_LowerTouchEvent += (s, e) =>
            {
                EventViewer.AddEventToViewer("MicLevel", e);

                this.microphoneEmulators[e.WidgetItemIndex].Level = e.SigArgs.Sig.UShortValue;
            };
        }

        /// <summary>
        /// Sets up the microphone emulators with the desired number of items.
        /// </summary>
        /// <param name="count">The number of microphones to be emulated.</param>
        private void SetupMicrophoneEmulators(ushort count)
        {
            this.microphoneEmulators = new MicrophoneEmulator[count];

            for (ushort i = 0; i < count; i++)
            {
                this.microphoneEmulators[i] = new MicrophoneEmulator($"Microphone {i + 1}");
            }
        }
    }
}
