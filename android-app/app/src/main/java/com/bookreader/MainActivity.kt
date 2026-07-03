package com.bookreader

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import com.bookreader.databinding.ActivityMainBinding
import java.io.File

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private val books = mutableListOf<BookItem>()
    private lateinit var adapter: BookAdapter

    private val filePicker = registerForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { uri ->
        uri?.let { openBook(it) }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setupRecyclerView()
        setupFab()
        loadBooks()
    }

    private fun setupRecyclerView() {
        adapter = BookAdapter(books) { book ->
            val intent = Intent(this, ReaderActivity::class.java).apply {
                putExtra("book_path", book.path)
                putExtra("book_type", book.type)
            }
            startActivity(intent)
        }
        
        binding.recyclerView.layoutManager = LinearLayoutManager(this)
        binding.recyclerView.adapter = adapter
    }

    private fun setupFab() {
        binding.fabAdd.setOnClickListener {
            openFilePicker()
        }
    }

    private fun openFilePicker() {
        filePicker.launch(arrayOf(
            "application/pdf",
            "application/epub+zip",
            "text/plain"
        ))
    }

    private fun openBook(uri: Uri) {
        val path = uri.toString()
        val type = when {
            uri.toString().endsWith(".pdf") -> "pdf"
            uri.toString().endsWith(".epub") -> "epub"
            else -> "txt"
        }
        
        val book = BookItem(
            title = File(uri.path ?: "Unknown").name,
            path = path,
            type = type
        )
        
        books.add(book)
        adapter.notifyItemInserted(books.size - 1)
        saveBooks()
        
        val intent = Intent(this, ReaderActivity::class.java).apply {
            putExtra("book_path", path)
            putExtra("book_type", type)
        }
        startActivity(intent)
    }

    private fun loadBooks() {
        // TODO: Load from SharedPreferences
    }

    private fun saveBooks() {
        // TODO: Save to SharedPreferences
    }
}

data class BookItem(
    val title: String,
    val path: String,
    val type: String
)
