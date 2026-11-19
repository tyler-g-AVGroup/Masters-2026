using System;

namespace Masters2026
{
    /// <summary>
    /// Contains details about a UI event.
    /// </summary>
    internal class EventItem
    {
        /// <summary>
        /// Initializes a new instance of the <see cref="EventItem"/> class.
        /// </summary>
        /// <param name="name">The name of the contract which triggered the event.</param>
        /// <param name="details">Details about the UI event. What was contained in the <see cref="EventArgs"/>.</param>
        internal EventItem(string name, string details)
        {
            this.Details = details;
            this.Name = name;
            this.TimeStamp = DateTime.Now;
        }

        /// <summary>
        /// Gets the details about the event.
        /// </summary>
        public string Details { get; private set; }

        /// <summary>
        /// Gets the name of the contract which triggered the event.
        /// </summary>
        public string Name { get; private set; }

        /// <summary>
        /// Gets the timestamp of when the event occurred.
        /// </summary>
        public DateTime TimeStamp { get; private set; }
    }
}
