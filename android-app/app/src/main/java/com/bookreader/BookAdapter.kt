package com.bookreader

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.bookreader.databinding.ItemBookBinding

class BookAdapter(
    private val books: List<BookItem>,
    private val onClick: (BookItem) -> Unit
) : RecyclerView.Adapter<BookAdapter.ViewHolder>() {

    class ViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val binding = ItemBookBinding.bind(view)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_book, parent, false)
        return ViewHolder(view)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val book = books[position]
        holder.binding.txtTitle.text = book.title
        holder.binding.txtType.text = when (book.type) {
            "pdf" -> "PDF"
            "epub" -> "EPUB"
            else -> "TXT"
        }
        holder.itemView.setOnClickListener { onClick(book) }
    }

    override fun getItemCount() = books.size
}
